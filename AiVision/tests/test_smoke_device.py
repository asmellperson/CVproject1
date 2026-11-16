"""烟雾设备接入的协议、能力边界、写后回读和凭据保护回归。"""
from dataclasses import replace
from threading import Event
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from AiVision.features.smoke_detection import device
from AiVision.features.smoke_detection.device_schema import (
    SmokeParametersUpdate, SmokeShieldPoint, SmokeShieldRegion, SmokeShieldUpdate,
)
from AiVision.features.smoke_detection.events import (
    SmokeProtocolError, iter_multipart, parse_smoke_event, parse_xml,
)


CAMERA = {"url": "rtsp://operator:sample%40password@192.0.2.10:554/Streaming/Channels/201"}
VALUE = {"device_scheme": "http", "device_port": 8080, "event_channel_id": 2, "thermal_channel_id": 2}
THERMAL = '<ThermalCap><isSupportFireDetection>true</isSupportFireDetection></ThermalCap>'
PARAMETER_CAP = '''<FireDetection><SmokeDetection><enabled>true</enabled>
    <sensitivity min="10" max="80">1</sensitivity><doubleCheckSensitivity min="1" max="100">50</doubleCheckSensitivity>
    <displaySmokeInfoOnStreamEnabled opt="true,false">true</displaySmokeInfoOnStreamEnabled>
    </SmokeDetection></FireDetection>'''
PARAMETER_CURRENT = '''<FireDetection xmlns="http://www.isapi.org/ver20/XMLSchema">
    <sensitivity>99</sensitivity><SmokeDetection><enabled>false</enabled><sensitivity>40</sensitivity>
    <doubleCheckSensitivity>50</doubleCheckSensitivity><displaySmokeInfoOnStreamEnabled>true</displaySmokeInfoOnStreamEnabled>
    <UnknownSmokeOption>keep</UnknownSmokeOption></SmokeDetection><Unknown>keep</Unknown></FireDetection>'''
OK = '<ResponseStatus><statusCode>1</statusCode></ResponseStatus>'
NOT_SUPPORT = '''<ResponseStatus xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">
    <statusCode>4</statusCode><statusString>Invalid Operation</statusString>
    <subStatusCode>notSupport</subStatusCode></ResponseStatus>'''
SHIELD_CAP = '''<SmokeShieldMask><enabled>true</enabled><SmokeShieldMaskRegionList size="4">
    <SmokeShieldMaskRegion><id min="1" max="4">1</id><enabled>true</enabled><showEnabled>true</showEnabled>
    <regionType opt="quadrilateral">quadrilateral</regionType></SmokeShieldMaskRegion>
    </SmokeShieldMaskRegionList></SmokeShieldMask>'''
SHIELD_CURRENT = '''<SmokeShieldMask xmlns="http://www.isapi.org/ver20/XMLSchema"><enabled>true</enabled>
    <normalizedScreenSize><normalizedScreenWidth>1000</normalizedScreenWidth>
    <normalizedScreenHeight>1000</normalizedScreenHeight></normalizedScreenSize><Unknown>keep</Unknown>
    <SmokeShieldMaskRegionList><SmokeShieldMaskRegion><id>1</id><showEnabled>true</showEnabled><enabled>true</enabled>
    <maskName>测试区</maskName><regionType>quadrilateral</regionType><UnknownRegion>keep</UnknownRegion>
    <RegionCoordinatesList><RegionCoordinates><positionX>100</positionX><positionY>900</positionY></RegionCoordinates>
    <RegionCoordinates><positionX>300</positionX><positionY>900</positionY></RegionCoordinates>
    <RegionCoordinates><positionX>300</positionX><positionY>600</positionY></RegionCoordinates>
    <RegionCoordinates><positionX>100</positionX><positionY>600</positionY></RegionCoordinates>
    </RegionCoordinatesList></SmokeShieldMaskRegion></SmokeShieldMaskRegionList></SmokeShieldMask>'''


def response(payload, status=200, content_type="application/xml"):
    result = Mock()
    result.status_code = status
    result.headers = {"Content-Type": content_type}
    body = payload.encode() if isinstance(payload, str) else payload
    result.iter_content.return_value = iter([body])
    result.raw.read1.side_effect = [body, b""]
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def client_with(responses, *, options=None, value=None):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    replies = iter(responses)
    session.request.side_effect = replies
    session.get.side_effect = replies
    factory = Mock(return_value=session)
    client = device.SmokeDeviceClient(CAMERA, value or VALUE, options, session_factory=factory)
    return client, session, factory


def smoke_xml(event_type="smokeDetection", state="active", channel=2, extra=""):
    return (f'<EventNotificationAlert xmlns="http://www.isapi.org/ver20/XMLSchema"><eventType>{event_type}</eventType>'
            f'<eventState>{state}</eventState><channelID>{channel}</channelID><dateTime>2026-11-16T08:00:00+08:00</dateTime>'
            f'<activePostCount>1</activePostCount>{extra}</EventNotificationAlert>').encode()


def multipart(payload, *, content_length=True, content_type="application/xml", closing=True):
    header = f"--boundary\r\nContent-Type: {content_type}\r\n".encode()
    if content_length:
        header += f"Content-Length: {len(payload)}\r\n".encode()
    return header + b"\r\n" + payload + (b"\r\n--boundary--\r\n" if closing else b"")


def test_parameter_reads_actual_supported_values_and_ranges():
    client, session, _ = client_with([response(THERMAL), response(PARAMETER_CAP), response(PARAMETER_CURRENT)])
    state = client.read_parameters()
    assert state.supported and state.channel_id == 2
    fields = {item.key: item for item in state.parameters}
    assert fields["enabled"].value is False
    assert fields["sensitivity"].value == 40
    assert (fields["sensitivity"].minimum, fields["sensitivity"].maximum) == (10, 80)
    assert "patrol_sensitivity" not in fields
    assert session.trust_env is False
    assert session.auth.username == "operator" and session.auth.password == "sample@password"
    assert "8080/ISAPI/Thermal/channels/2/fireDetection" in session.request.call_args.args[1]
    assert session.request.call_args.kwargs["allow_redirects"] is False


def test_parameter_write_preserves_unknown_and_fire_fields_and_confirms_readback():
    updated = PARAMETER_CURRENT.replace("<sensitivity>40</sensitivity>", "<sensitivity>60</sensitivity>")
    client, session, _ = client_with([response(THERMAL), response(PARAMETER_CAP), response(PARAMETER_CURRENT),
                                    response(OK), response(updated)])
    result = client.write_parameters(SmokeParametersUpdate(values={"sensitivity": 60}))
    payload = session.request.call_args_list[3].kwargs["data"]
    assert b"<Unknown>keep</Unknown>" in payload and b"<UnknownSmokeOption>keep</UnknownSmokeOption>" in payload
    assert b"<sensitivity>99</sensitivity>" in payload
    assert next(item for item in result.parameters if item.key == "sensitivity").value == 60


def test_global_only_camera_exposes_explicit_fire_and_smoke_switch():
    capabilities = '<FireDetection><smokeFireEnabled>true</smokeFireEnabled></FireDetection>'
    current = '<FireDetection><smokeFireEnabled>false</smokeFireEnabled><sensitivity>99</sensitivity></FireDetection>'
    client, _, _ = client_with([response(THERMAL), response(capabilities), response(current)])
    state = client.read_parameters()
    assert state.supported and state.global_enabled is False
    assert len(state.parameters) == 1 and state.parameters[0].key == "global_enabled"
    assert state.parameters[0].value is False and "火点" in state.parameters[0].label


def test_global_switch_write_preserves_all_other_fire_fields_and_reads_back():
    capabilities = '<FireDetection><smokeFireEnabled>true</smokeFireEnabled></FireDetection>'
    current = ('<FireDetection xmlns="http://www.isapi.org/ver20/XMLSchema"><smokeFireEnabled>false</smokeFireEnabled>'
               '<enabled>false</enabled><sensitivity>99</sensitivity><Unknown>keep</Unknown></FireDetection>')
    actual = current.replace('<smokeFireEnabled>false', '<smokeFireEnabled>true')
    client, session, _ = client_with([response(THERMAL), response(capabilities), response(current),
                                    response(OK), response(actual)])
    result = client.write_parameters(SmokeParametersUpdate(values={"global_enabled": True}))
    payload = session.request.call_args_list[3].kwargs["data"]
    assert b"<smokeFireEnabled>true</smokeFireEnabled>" in payload
    assert b"<enabled>false</enabled>" in payload and b"<sensitivity>99</sensitivity>" in payload
    assert b"<Unknown>keep</Unknown>" in payload and b"SmokeDetection" not in payload
    assert result.global_enabled is True and result.parameters[0].value is True


@pytest.mark.parametrize("cap_has_global,current_has_global", [(True, False), (False, True)])
def test_global_switch_requires_both_capability_and_current_node(cap_has_global, current_has_global):
    capabilities = PARAMETER_CAP.replace('</FireDetection>', '<smokeFireEnabled>true</smokeFireEnabled></FireDetection>') if cap_has_global else PARAMETER_CAP
    current = PARAMETER_CURRENT.replace('</FireDetection>', '<smokeFireEnabled>false</smokeFireEnabled></FireDetection>') if current_has_global else PARAMETER_CURRENT
    client, session, _ = client_with([response(THERMAL), response(capabilities), response(current)])
    with pytest.raises(device.SmokeDeviceError, match="未确认"):
        client.write_parameters(SmokeParametersUpdate(values={"global_enabled": True}))
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


def test_global_switch_requires_boolean_and_actual_readback_confirmation():
    capabilities = '<FireDetection><smokeFireEnabled>true</smokeFireEnabled></FireDetection>'
    current = '<FireDetection><smokeFireEnabled>false</smokeFireEnabled></FireDetection>'
    client, session, _ = client_with([response(THERMAL), response(capabilities), response(current)])
    with pytest.raises(device.SmokeDeviceError, match="类型"):
        client.write_parameters(SmokeParametersUpdate(values={"global_enabled": 1}))
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    client, _, _ = client_with([response(THERMAL), response(capabilities), response(current), response(OK), response(current)])
    with pytest.raises(device.SmokeDeviceError, match="回读"):
        client.write_parameters(SmokeParametersUpdate(values={"global_enabled": True}))


def test_global_switch_does_not_invent_independent_smoke_enable():
    capabilities = PARAMETER_CAP.replace('<enabled>true</enabled>', '').replace('</FireDetection>', '<smokeFireEnabled>true</smokeFireEnabled></FireDetection>')
    current = PARAMETER_CURRENT.replace('<enabled>false</enabled>', '').replace('</FireDetection>', '<smokeFireEnabled>false</smokeFireEnabled></FireDetection>')
    client, _, _ = client_with([response(THERMAL), response(capabilities), response(current)])
    fields = {item.key for item in client.read_parameters().parameters}
    assert "global_enabled" in fields and "enabled" not in fields and "sensitivity" in fields


def test_parameter_update_accepts_all_declared_fields_but_rejects_excess():
    values = {"global_enabled": True, "enabled": True, "sensitivity": 40, "patrol_sensitivity": 50,
              "double_check_sensitivity": 50, "display_smoke_info": True,
              "alarm_strategy": "any", "device_alarm_interval": 10,
              "image_quality": "best", "high_sensitivity_enabled": True}
    assert len(SmokeParametersUpdate(values=values).values) == 10
    with pytest.raises(ValidationError):
        SmokeParametersUpdate(values={**values, "unknown": 1})


@pytest.mark.parametrize("values", [{"sensitivity": 81}, {"sensitivity": True}, {"enabled": 1}, {"unknown": 1}])
def test_invalid_or_unsupported_parameter_never_writes(values):
    client, session, _ = client_with([response(THERMAL), response(PARAMETER_CAP), response(PARAMETER_CURRENT)])
    with pytest.raises(device.SmokeDeviceError):
        client.write_parameters(SmokeParametersUpdate(values=values))
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


def test_parameter_write_requires_business_success_and_matching_readback():
    client, _, _ = client_with([response(THERMAL), response(PARAMETER_CAP), response(PARAMETER_CURRENT),
                              response('<ResponseStatus><statusCode>4</statusCode></ResponseStatus>')])
    with pytest.raises(device.SmokeDeviceError, match="拒绝"):
        client.write_parameters(SmokeParametersUpdate(values={"sensitivity": 60}))
    client, _, _ = client_with([response(THERMAL), response(PARAMETER_CAP), response(PARAMETER_CURRENT),
                              response(OK), response(PARAMETER_CURRENT)])
    with pytest.raises(device.SmokeDeviceError, match="回读"):
        client.write_parameters(SmokeParametersUpdate(values={"sensitivity": 60}))


def test_missing_parameter_range_not_offered_as_editable():
    cap = PARAMETER_CAP.replace('min="10" max="80"', '')
    client, _, _ = client_with([response(THERMAL), response(cap), response(PARAMETER_CURRENT)])
    assert "sensitivity" not in {item.key for item in client.read_parameters().parameters}


def test_unsupported_capabilities_do_not_invent_device_defaults():
    client, session, _ = client_with([response(THERMAL.replace("true", "false"))])
    state = client.read_parameters()
    assert not state.supported and state.parameters == []
    assert session.request.call_count == 1


def test_device_403_not_support_is_not_reported_as_bad_credentials():
    client, session, _ = client_with([response(NOT_SUPPORT, 403)])
    with pytest.raises(device.SmokeDeviceError, match="参数通道") as error:
        client._request("GET", "/ISAPI/Thermal/channels/1/fireDetection/capabilities")
    assert error.value.unsupported and error.value.device_status == 403
    assert "密码" not in str(error.value)
    assert session.request.call_count == 1


def test_optional_403_not_support_returns_no_capability_without_switching_channel():
    client, session, _ = client_with([response(THERMAL), response(NOT_SUPPORT, 403)])
    state = client.read_parameters()
    assert not state.supported and state.parameters == [] and "参数通道" in state.message
    assert session.request.call_count == 2
    assert session.request.call_args.args[1].endswith("/channels/2/fireDetection/capabilities")
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


@pytest.mark.parametrize("status,payload", [
    (401, NOT_SUPPORT),
    (403, '<ResponseStatus><statusCode>4</statusCode><subStatusCode>badAuthorization</subStatusCode></ResponseStatus>'),
    (403, '<ResponseStatus><statusCode>4</statusCode><subStatusCode>lowPrivilege</subStatusCode></ResponseStatus>'),
    (403, NOT_SUPPORT.replace('<statusCode>4', '<statusCode>3')),
    (403, NOT_SUPPORT.replace('ResponseStatus', 'UnknownResponse')),
    (403, '<ResponseStatus><statusCode>4</statusCode><subStatusCode>notSupport'),
    (403, '<!DOCTYPE a [<!ENTITY x "notSupport">]><ResponseStatus><statusCode>4</statusCode><subStatusCode>&x;</subStatusCode></ResponseStatus>'),
])
def test_other_denials_are_not_suppressed_as_unsupported(status, payload):
    reply = response(payload, status)
    client, session, _ = client_with([reply])
    with pytest.raises(device.SmokeDeviceError, match="拒绝访问") as error:
        client._optional_get("/ISAPI/Thermal/channels/2/fireDetection/capabilities")
    assert error.value.device_status == status and error.value.unsupported is False
    assert session.request.call_count == 1
    if status == 401:
        reply.iter_content.assert_not_called()


def test_403_error_xml_uses_the_response_size_limit():
    client, session, _ = client_with([response(NOT_SUPPORT, 403)],
                                    options=replace(device.SmokeDeviceOptions(), max_response_bytes=32))
    with pytest.raises(device.SmokeDeviceError, match="大小") as error:
        client._optional_get("/ISAPI/Thermal/channels/2/fireDetection/capabilities")
    assert error.value.unsupported is False
    assert session.request.call_count == 1


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_device_http_failures_are_sanitized(status):
    client, _, _ = client_with([response("password", status)])
    with pytest.raises(device.SmokeDeviceError) as error:
        client.read_parameters()
    assert "password" not in str(error.value) and "192.0.2.10" not in str(error.value)


def test_network_errors_do_not_disclose_url_credentials():
    client, session, _ = client_with([])
    session.request.side_effect = device.requests.Timeout(CAMERA["url"])
    with pytest.raises(device.SmokeDeviceError, match="超时") as error:
        client.read_parameters()
    assert "sample" not in str(error.value) and error.value.__suppress_context__


def test_response_limit_and_entity_rejection():
    client, _, _ = client_with([response(THERMAL)], options=replace(device.SmokeDeviceOptions(), max_response_bytes=8))
    with pytest.raises(device.SmokeDeviceError, match="大小"):
        client.read_parameters()
    declaration = '<!DOCTYPE a [<!ENTITY x "abc">]><a>&x;</a>'
    for payload in (declaration.encode(), declaration.encode("utf-16")):
        with pytest.raises(SmokeProtocolError):
            parse_xml(payload)
    with pytest.raises(SmokeProtocolError, match="非事件"):
        parse_smoke_event(b"<ResponseStatus><statusCode>4</statusCode></ResponseStatus>")


def test_shield_coordinate_origin_and_actual_capabilities():
    client, _, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT)])
    state = client.read_shields()
    assert state.supported and state.writable
    assert (state.max_regions, state.min_points, state.max_points) == (4, 4, 4)
    assert state.regions[0].points[0].x == .1
    assert state.regions[0].points[0].y == pytest.approx(.1)


def test_missing_coordinate_size_makes_regions_read_only():
    current = SHIELD_CURRENT.replace("<normalizedScreenWidth>1000</normalizedScreenWidth>", "<normalizedScreenWidth>0</normalizedScreenWidth>")
    client, _, _ = client_with([response(SHIELD_CAP), response(current)])
    assert not client.read_shields().writable


def test_invalid_shield_enabled_value_is_not_presented_as_disabled():
    current = SHIELD_CURRENT.replace("<enabled>true</enabled>", "<enabled>unknown</enabled>", 1)
    client, _, _ = client_with([response(SHIELD_CAP), response(current)])
    with pytest.raises(device.SmokeDeviceError, match="开关状态"):
        client.read_shields()


def test_region_write_keeps_device_fields_and_confirms_coordinates():
    client, session, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT), response(OK), response(SHIELD_CURRENT)])
    region = SmokeShieldRegion(id=1, name="测试区", points=[
        SmokeShieldPoint(x=.1, y=.1), SmokeShieldPoint(x=.3, y=.1),
        SmokeShieldPoint(x=.3, y=.4), SmokeShieldPoint(x=.1, y=.4)])
    result = client.write_shields(SmokeShieldUpdate(enabled=True, regions=[region]))
    payload = session.request.call_args_list[2].kwargs["data"]
    assert b"<Unknown>keep</Unknown>" in payload and b"<UnknownRegion>keep</UnknownRegion>" in payload
    assert b"<positionY>900</positionY>" in payload
    assert result.regions[0].name == "测试区"


def test_shield_rejects_triangle_before_write_for_quadrilateral_device():
    client, session, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT)])
    region = SmokeShieldRegion(id=1, points=[SmokeShieldPoint(x=.1, y=.1), SmokeShieldPoint(x=.3, y=.1), SmokeShieldPoint(x=.3, y=.4)])
    with pytest.raises(device.SmokeDeviceError, match="顶点"):
        client.write_shields(SmokeShieldUpdate(enabled=True, regions=[region]))
    assert session.request.call_count == 2


def test_shield_rejects_self_crossing_polygon():
    with pytest.raises(ValidationError):
        SmokeShieldRegion(id=1, points=[SmokeShieldPoint(x=.0, y=.0), SmokeShieldPoint(x=1., y=1.),
                                     SmokeShieldPoint(x=.0, y=1.), SmokeShieldPoint(x=1., y=.0)])


def test_shield_rejects_quantization_degenerate_region_without_writing():
    client, session, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT)])
    region = SmokeShieldRegion(id=1, name="测试区", points=[
        SmokeShieldPoint(x=.1001, y=.1), SmokeShieldPoint(x=.1002, y=.1),
        SmokeShieldPoint(x=.1002, y=.4), SmokeShieldPoint(x=.1001, y=.4)])
    with pytest.raises(device.SmokeDeviceError, match="退化"):
        client.write_shields(SmokeShieldUpdate(enabled=True, regions=[region]))
    assert session.request.call_count == 2


def test_shield_hidden_regions_cannot_be_replaced_by_client():
    current = SHIELD_CURRENT.replace("<showEnabled>true</showEnabled>", "<showEnabled>false</showEnabled>")
    client, session, _ = client_with([response(SHIELD_CAP), response(current)])
    region = SmokeShieldRegion(id=1, points=[
        SmokeShieldPoint(x=.1, y=.1), SmokeShieldPoint(x=.3, y=.1),
        SmokeShieldPoint(x=.3, y=.4), SmokeShieldPoint(x=.1, y=.4)])
    with pytest.raises(device.SmokeDeviceError, match="未开放"):
        client.write_shields(SmokeShieldUpdate(enabled=True, regions=[region]))
    assert session.request.call_count == 2


def test_shield_preserves_hidden_device_regions_in_bulk_update():
    current = SHIELD_CURRENT.replace("<showEnabled>true</showEnabled>", "<showEnabled>false</showEnabled>")
    client, session, _ = client_with([response(SHIELD_CAP), response(current), response(OK), response(current)])
    assert client.write_shields(SmokeShieldUpdate(enabled=True, regions=[])).regions == []
    assert b"<showEnabled>false</showEnabled>" in session.request.call_args_list[2].kwargs["data"]


@pytest.mark.parametrize("event_type", ["fireDetection", "smokeAndFireDetection", "thermometry", "smokingDetection", "videoloss"])
def test_non_smoke_events_are_not_reclassified(event_type):
    assert parse_smoke_event(smoke_xml(event_type)) is None


def test_event_identity_and_inactive_state():
    first = parse_smoke_event(smoke_xml())
    repeated = parse_smoke_event(smoke_xml())
    assert first.active and first.channel_id == 2 and first.event_id == repeated.event_id
    assert parse_smoke_event(smoke_xml(state="inactive")).active is False
    assert parse_smoke_event(smoke_xml(extra="<eventID>camera-event-1</eventID>")).event_id == "camera-event-1"


@pytest.mark.parametrize("payload", [smoke_xml().replace(b"+08:00", b""), smoke_xml(channel=0), smoke_xml(state="unknown")])
def test_incomplete_smoke_event_is_rejected(payload):
    with pytest.raises(SmokeProtocolError):
        parse_smoke_event(payload)


@pytest.mark.parametrize("has_length", [True, False])
def test_multipart_handles_every_byte_boundary_split(has_length):
    body = smoke_xml()
    stream = multipart(body, content_length=has_length)
    parts = list(iter_multipart((stream[index:index + 1] for index in range(len(stream))), 'multipart/mixed; boundary="boundary"'))
    assert len(parts) == 1 and parts[0].body == body


def test_multipart_accepts_binary_parts_without_xml_assumptions():
    body = b"\xff\xd8\x00binary\r\n"
    parts = list(iter_multipart([multipart(body, content_type="image/jpeg")], "multipart/mixed; boundary=boundary"))
    assert parts[0].body == body and parts[0].content_type == "image/jpeg"


@pytest.mark.parametrize("stream", [b"--boundary\r\nContent-Length: 999999999\r\n\r\n",
    b"--boundary\r\nContent-Length: 10\r\nContent-Length: 1\r\n\r\nA",
    b"--boundary\r\nContent-Type: application/xml\r\n\r\n" + b"A" * 100])
def test_multipart_limits_and_truncated_parts(stream):
    with pytest.raises(SmokeProtocolError):
        list(iter_multipart([stream], "multipart/mixed; boundary=boundary", maximum_part_bytes=16))


def test_subscription_filters_channel_but_reports_activity_and_connection():
    other = multipart(smoke_xml(channel=1), closing=False)
    # Content-Length 允许在下一条报文前就交付告警，不等待抓拍或心跳。
    body = other + b"\r\n" + multipart(smoke_xml())
    client, session, _ = client_with([response(body, content_type="multipart/mixed; boundary=boundary")])
    connected, activity = Mock(), Mock()
    events = list(client.iter_events(Event(), connected, activity))
    assert len(events) == 1 and events[0].channel_id == 2
    connected.assert_called_once()
    assert activity.call_count == 2
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_successful_event_stream_is_not_read_before_connection_callback():
    reply = response(multipart(smoke_xml()), content_type="multipart/mixed; boundary=boundary")
    client, _, _ = client_with([reply])

    def connected():
        reply.iter_content.assert_not_called()
        reply.raw.read1.assert_not_called()

    events = list(client.iter_events(Event(), on_connected=connected))
    assert len(events) == 1
    reply.iter_content.assert_not_called()
    assert reply.raw.read1.call_count == 1
    reply.raw.read1.assert_called_with(device.STREAM_CHUNK_BYTES, decode_content=True)


def test_subscription_cancel_closes_response_without_raw_error():
    client, _, _ = client_with([])
    result, session = Mock(), Mock()
    client._active_response, client._active_session = result, session
    client.close()
    result.close.assert_called_once()
    session.close.assert_called_once()
    assert list(client.iter_events(Event())) == []


@pytest.mark.parametrize("event_type", ["fireDetection", "smokeAndFireDetection"])
def test_unverified_fire_events_warn_without_synthesizing_smoke(event_type):
    client, _, _ = client_with([response(multipart(smoke_xml(event_type)),
                                        content_type="multipart/mixed; boundary=boundary")])
    warning, activity = Mock(), Mock()
    assert list(client.iter_events(Event(), on_activity=activity, on_protocol_warning=warning)) == []
    warning.assert_called_once()
    assert "尚未核验" in warning.call_args.args[0]
    activity.assert_called_once()


def test_unverified_fire_from_other_channel_does_not_warn_this_camera():
    client, _, _ = client_with([response(multipart(smoke_xml("fireDetection", channel=1)),
                                        content_type="multipart/mixed; boundary=boundary")])
    warning = Mock()
    assert list(client.iter_events(Event(), on_protocol_warning=warning)) == []
    warning.assert_not_called()


def test_confirmed_smoke_event_clears_protocol_warning():
    stream = multipart(smoke_xml("smokeAndFireDetection"), closing=False) + b"\r\n" + multipart(smoke_xml())
    client, _, _ = client_with([response(stream, content_type="multipart/mixed; boundary=boundary")])
    warning = Mock()
    events = list(client.iter_events(Event(), on_protocol_warning=warning))
    assert len(events) == 1 and events[0].event_type == "smokeDetection"
    assert warning.call_count == 2 and warning.call_args.args == ("",)


def test_invalid_target_never_opens_network():
    factory = Mock()
    with pytest.raises(device.SmokeDeviceError):
        device.SmokeDeviceClient({"url": "http://example.invalid"}, VALUE, session_factory=factory)
    factory.assert_not_called()


def test_picture_uses_exact_configuration_channel_and_validates_jpeg():
    import cv2
    import numpy as np
    ok, encoded = cv2.imencode(".jpg", np.zeros((4, 6, 3), dtype=np.uint8))
    assert ok
    payload = encoded.tobytes()
    client, session, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT),
                                    response(payload, content_type="image/jpeg")])
    assert client.read_picture() == payload
    assert session.get.call_args.args[0].endswith("/ISAPI/Streaming/channels/201/picture")


def test_picture_rejects_xml_body_and_oversized_dimensions():
    client, _, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT),
                               response("<ResponseStatus/>", content_type="application/xml")])
    with pytest.raises(device.SmokeDeviceError, match="JPEG"):
        client.read_picture()
    body = b"\xff\xd8\xff\xc0\x00\x08\x08\xff\xff\xff\xff\x00"
    with pytest.raises(device.SmokeDeviceError, match="尺寸"):
        device._jpeg_dimensions(body)


EXTENDED_CAP = PARAMETER_CAP.replace('</SmokeDetection>', '''
    <alarmInterval min="1" max="300">1</alarmInterval><imgQuality opt="best,good,general">best</imgQuality>
    <highSensitivityEnabled opt="true,false">true</highSensitivityEnabled></SmokeDetection>''').replace(
    '</FireDetection>', '<AlarmStrategy><strategyType opt="any,multiSystem,appointFire,appointSmoke">any</strategyType></AlarmStrategy></FireDetection>')
EXTENDED_CURRENT = PARAMETER_CURRENT.replace('</SmokeDetection>', '''
    <alarmInterval>1</alarmInterval><imgQuality>best</imgQuality>
    <highSensitivityEnabled>true</highSensitivityEnabled></SmokeDetection>''').replace(
    '</FireDetection>', '<AlarmStrategy><strategyType>appointFire</strategyType></AlarmStrategy></FireDetection>')


def test_extended_parameters_show_actual_choices_ranges_and_fire_only_warning():
    client, session, _ = client_with([response(THERMAL), response(EXTENDED_CAP), response(EXTENDED_CURRENT)])
    state = client.read_parameters()
    fields = {item.key: item for item in state.parameters}
    assert fields['alarm_strategy'].value == 'appointFire'
    assert [choice.value for choice in fields['alarm_strategy'].choices] == ['any', 'multiSystem', 'appointFire', 'appointSmoke']
    assert (fields['device_alarm_interval'].minimum, fields['device_alarm_interval'].maximum) == (1, 300)
    assert fields['image_quality'].value == 'best' and fields['high_sensitivity_enabled'].value is True
    assert len(state.warnings) == 1 and '烟雾报警不会上传' in state.warnings[0]
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)


def test_extended_parameter_save_preserves_enum_case_unknown_fields_and_confirms_readback():
    actual = EXTENDED_CURRENT.replace('appointFire', 'multiSystem').replace('<alarmInterval>1</alarmInterval>', '<alarmInterval>30</alarmInterval>').replace('<imgQuality>best</imgQuality>', '<imgQuality>good</imgQuality>').replace('<highSensitivityEnabled>true', '<highSensitivityEnabled>false')
    client, session, _ = client_with([response(THERMAL), response(EXTENDED_CAP), response(EXTENDED_CURRENT), response(OK), response(actual)])
    result = client.write_parameters(SmokeParametersUpdate(values={
        'alarm_strategy': 'multiSystem', 'device_alarm_interval': 30,
        'image_quality': 'good', 'high_sensitivity_enabled': False,
    }))
    payload = session.request.call_args_list[3].kwargs['data']
    assert b'<strategyType>multiSystem</strategyType>' in payload
    assert b'<Unknown>keep</Unknown>' in payload and b'<sensitivity>99</sensitivity>' in payload
    assert not result.warnings


@pytest.mark.parametrize('values', [
    {'alarm_strategy': 'invented'}, {'alarm_strategy': True}, {'image_quality': 'unknown'},
    {'device_alarm_interval': 0}, {'device_alarm_interval': 301}, {'device_alarm_interval': True},
    {'high_sensitivity_enabled': 1},
])
def test_extended_parameters_reject_unconfirmed_values_before_put(values):
    client, session, _ = client_with([response(THERMAL), response(EXTENDED_CAP), response(EXTENDED_CURRENT)])
    with pytest.raises(device.SmokeDeviceError):
        client.write_parameters(SmokeParametersUpdate(values=values))
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)


def test_enum_requires_reported_choices_and_matching_readback():
    capabilities = EXTENDED_CAP.replace('opt="any,multiSystem,appointFire,appointSmoke"', 'opt="appointFire,appointSmoke"')
    client, session, _ = client_with([response(THERMAL), response(capabilities), response(EXTENDED_CURRENT)])
    with pytest.raises(device.SmokeDeviceError, match='范围'):
        client.write_parameters(SmokeParametersUpdate(values={'alarm_strategy': 'any'}))
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)
    client, _, _ = client_with([response(THERMAL), response(EXTENDED_CAP), response(EXTENDED_CURRENT), response(OK), response(EXTENDED_CURRENT)])
    with pytest.raises(device.SmokeDeviceError, match='回读'):
        client.write_parameters(SmokeParametersUpdate(values={'alarm_strategy': 'any'}))


def test_shields_use_confirmed_visible_channel_independently_from_parameters():
    cap = SHIELD_CAP.replace(' size="4"', '').replace('max="4"', 'max="50"')
    current = SHIELD_CURRENT.replace('<SmokeShieldMaskRegionList>', '<SmokeShieldMaskRegionList size="50">')
    client, session, _ = client_with([response(cap), response(current)], value={**VALUE, 'event_channel_id': 1})
    result = client.read_shields()
    assert result.supported and result.writable and result.channel_id == 1 and result.max_regions == 50
    assert all('/channels/1/' in call.args[1] for call in session.request.call_args_list)
    assert client._target.thermal_channel_id == 2


def test_shield_picture_and_write_both_use_capability_confirmed_channel():
    import cv2
    import numpy as np
    ok, encoded = cv2.imencode('.jpg', np.zeros((4, 6, 3), dtype=np.uint8))
    assert ok
    client, session, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT), response(encoded.tobytes(), content_type='image/jpeg')], value={**VALUE, 'event_channel_id': 1})
    client.read_picture()
    assert session.get.call_args.args[0].endswith('/channels/101/picture')
    client, session, _ = client_with([response(SHIELD_CAP), response(SHIELD_CURRENT), response(OK), response(SHIELD_CURRENT)], value={**VALUE, 'event_channel_id': 1})
    region = client._shield_state(parse_xml(SHIELD_CAP.encode()), parse_xml(SHIELD_CURRENT.encode())).regions[0]
    result = client.write_shields(SmokeShieldUpdate(enabled=True, regions=[region]))
    assert result.channel_id == 1
    assert all('/channels/1/' in call.args[1] for call in session.request.call_args_list)


def test_shield_channel_probe_only_skips_explicitly_unsupported_interface():
    client, session, _ = client_with([response(NOT_SUPPORT, 403), response(SHIELD_CAP), response(SHIELD_CURRENT)], value={**VALUE, 'event_channel_id': 1})
    assert client.read_shields().channel_id == 2
    assert '/channels/1/' in session.request.call_args_list[0].args[1]
    client, session, _ = client_with([response('<ResponseStatus/>', 403)], value={**VALUE, 'event_channel_id': 1})
    with pytest.raises(device.SmokeDeviceError, match='拒绝访问'):
        client.read_shields()
    assert session.request.call_count == 1


def test_raw_stream_timeout_is_sanitized():
    from urllib3.exceptions import ReadTimeoutError
    reply = response(b'', content_type='multipart/mixed; boundary=boundary')
    reply.raw.read1.side_effect = ReadTimeoutError(None, 'secret-url', 'secret-password')
    client, _, _ = client_with([reply])
    with pytest.raises(device.SmokeDeviceError) as caught:
        list(client.iter_events(Event()))
    assert 'secret' not in str(caught.value)


def test_small_non_chunked_http_event_arrives_before_stream_closes():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    release, complete = Event(), Event()
    received, failures = [], []
    payload = multipart(smoke_xml(), closing=False)
    assert len(payload) < device.STREAM_CHUNK_BYTES

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/mixed; boundary=boundary')
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()
            # 模拟摄像头持续连接；不能靠关闭连接才交付这条小事件。
            release.wait(3)
            self.close_connection = True

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    server_thread.start()
    client = device.SmokeDeviceClient(
        {'url': 'rtsp://operator:sample@127.0.0.1/Streaming/Channels/201'},
        {**VALUE, 'device_port': server.server_port},
        device.SmokeDeviceOptions(stream_timeout_seconds=2.0),
    )

    def receive():
        events = client.iter_events(Event())
        try:
            received.append(next(events))
        except Exception as exc:
            failures.append(type(exc).__name__)
        finally:
            events.close()
            complete.set()

    reader = Thread(target=receive, daemon=True)
    try:
        reader.start()
        assert complete.wait(1), '小报文被HTTP缓冲，未在持续连接中及时交付'
        assert not failures and received[0].active
        assert not release.is_set()
    finally:
        release.set()
        reader.join(3)
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(1)
