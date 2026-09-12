"""Artemis 协议和人员图片读取测试；凭据、人员和图片字节均为测试夹具。"""
import base64
import hashlib
import hmac
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from AiVision.connectors.hikvision import (
    ArtemisSigner, HikvisionClient, HikvisionConfig, HikvisionError, HikvisionPersons, PersonPhoto,
)
from AiVision.connectors.hikvision.persons import PERSON_INFO_PATH, PERSON_LIST_PATH, PERSON_PICTURE_PATH

TEST_KEY = "test-app-key"
TEST_SECRET = "test-app-secret"
TEST_URI = "/pic?opaque=value*with=significant+characters"
TEST_PERSON = {
    "personId": "test-person", "personName": "测试人员", "jobNo": "test-job",
    "personPhoto": {"picUri": TEST_URI, "serverIndexCode": "test-picture-server"},
}
PICTURE_BYTES = b"\xff\xd8\xfftest-picture-payload"


def response(status=200, *, payload=None, body=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {"Content-Type": "application/json"})
    result._content = body if body is not None else json.dumps(payload).encode("utf-8")
    result._content_consumed = True
    return result


@pytest.fixture
def transport(monkeypatch):
    replies, calls = [], []

    def send(session, request, **kwargs):
        calls.append((session, request, kwargs))
        assert kwargs["allow_redirects"] is False
        assert replies, "Unexpected outbound request"
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        item.request, item.url = request, request.url
        return item

    monkeypatch.setattr(requests.Session, "send", send)
    return replies, calls


def config(**overrides):
    return HikvisionConfig(base_url="https://hik.example", app_key=TEST_KEY, app_secret=TEST_SECRET, **overrides)


def test_signer_matches_fixed_protocol_vector_and_does_not_expose_credentials():
    signer = ArtemisSigner(TEST_KEY, TEST_SECRET)
    headers = signer.sign("POST", "/artemis/api/resource/v1/person/personList", b'{"pageNo":1,"pageSize":10}',
                          timestamp_ms=1700000000000, nonce="test-nonce")
    assert headers["Content-MD5"] == "kxdxk7rbAsrzSIWgEwhH4w=="
    assert headers["Date"] == "Tue, 14 Nov 2023 22:13:20 GMT"
    assert headers["x-ca-signature-headers"] == "x-ca-key,x-ca-nonce,x-ca-timestamp"
    assert headers["x-ca-signature"] == "25bU1aBQEZvjq26NaFF8pn5JZDu4WZ+jdztsYpHH8uA="
    assert TEST_SECRET not in repr(headers)
    assert TEST_KEY not in repr(signer)
    assert TEST_SECRET not in repr(config())


def test_sent_utf8_body_and_headers_match_signature_and_fresh_nonce(transport):
    replies, calls = transport
    replies.extend(response(payload={"code": "0", "data": {}}) for _ in range(2))
    with HikvisionClient(config()) as client:
        for _ in range(2):
            client.post_json(PERSON_INFO_PATH, {"personId": "人员"})
    for _, request, options in calls:
        body = request.body
        assert body == '{"personId":"人员"}'.encode("utf-8")
        assert request.headers["Content-MD5"] == base64.b64encode(hashlib.md5(body).digest()).decode()
        canonical = "POST\n*/*\n" + request.headers["Content-MD5"] + "\napplication/json\n"
        canonical += request.headers["Date"] + "\n"
        for key in ("x-ca-key", "x-ca-nonce", "x-ca-timestamp"):
            canonical += key + ":" + request.headers[key] + "\n"
        canonical += "/artemis" + PERSON_INFO_PATH
        expected = base64.b64encode(hmac.digest(TEST_SECRET.encode(), canonical.encode(), "sha256")).decode()
        assert request.headers["x-ca-signature"] == expected
        assert options["timeout"] == (8.0, 25.0)
        assert options["verify"] is True
    assert calls[0][1].headers["x-ca-nonce"] != calls[1][1].headers["x-ca-nonce"]


def test_person_list_detail_and_missing_person_code_are_typed(transport):
    replies, calls = transport
    replies.extend([
        response(payload={"code": "0", "data": {"total": 21, "pageNo": 2, "pageSize": 10, "list": [TEST_PERSON]}}),
        response(payload={"code": "0", "data": TEST_PERSON}),
    ])
    with HikvisionClient(config()) as client:
        persons = HikvisionPersons(client)
        page = persons.list_persons(page_no=2, page_size=10)
        person = persons.get_person(page.persons[0].person_id)
    assert (page.total, page.page_no, len(page.persons)) == (21, 2, 1)
    assert person == page.persons[0]
    assert person.person_code is None
    assert person.job_no == "test-job"
    assert person.person_photo.pic_uri == TEST_URI
    assert json.loads(calls[0][1].body) == {"pageNo": 2, "pageSize": 10}
    assert json.loads(calls[1][1].body) == {"personId": "test-person"}
    assert "测试人员" not in repr(person)


@pytest.mark.parametrize("organization_fields,expected", [
    ({"orgIndexCode": "test-org"}, "test-org"),
    ({}, None),
])
def test_person_list_org_index_code(transport, organization_fields, expected):
    replies, _ = transport
    replies.append(response(payload={"code": "0", "data": {
        "total": 1, "pageNo": 1, "pageSize": 10,
        "list": [{**TEST_PERSON, **organization_fields}],
    }}))
    with HikvisionClient(config()) as client:
        page = HikvisionPersons(client).list_persons()
    assert page.persons[0].org_index_code == expected


@pytest.mark.parametrize("organization_fields,expected", [
    ({"orgIndexCode": "test-org"}, "test-org"),
    ({}, None),
])
def test_person_info_org_index_code(transport, organization_fields, expected):
    replies, _ = transport
    replies.append(response(payload={"code": "0", "data": {**TEST_PERSON, **organization_fields}}))
    with HikvisionClient(config()) as client:
        person = HikvisionPersons(client).get_person("test-person")
    assert person.org_index_code == expected


def test_picture_uses_official_parameters_and_separate_unsigned_download(transport):
    replies, calls = transport
    target = "https://hik.example:6114" + TEST_URI + "&AccessKeyId=test-access&Expires=123&Signature=test-signature"
    replies.extend([
        response(302, headers={"Location": target}, body=b""),
        response(body=PICTURE_BYTES, headers={"Content-Type": "image/jpeg; charset=binary"}),
    ])
    with HikvisionClient(config(verify_tls=False)) as client:
        picture = HikvisionPersons(client).get_picture(PersonPhoto.model_validate(TEST_PERSON["personPhoto"]))
    assert picture.content == PICTURE_BYTES
    assert picture.content_type == "image/jpeg"
    assert picture.size_bytes == len(PICTURE_BYTES)
    api_session, api_request, _ = calls[0]
    picture_session, download, options = calls[1]
    assert api_request.url == "https://hik.example/artemis/api/resource/v1/person/picture"
    assert json.loads(api_request.body) == {"picUri": TEST_URI, "serverIndexCode": "test-picture-server"}
    assert download.method == "GET" and download.url == target
    assert api_session is not picture_session
    assert not api_session.trust_env and not picture_session.trust_env
    assert not any(key.lower().startswith("x-ca-") for key in download.headers)
    assert "Authorization" not in download.headers and "Cookie" not in download.headers
    assert options["verify"] is False


def test_relative_picture_redirects_resolve_against_response_url(transport):
    replies, calls = transport
    replies.extend([
        response(302, headers={"Location": "photo?Signature=first"}),
        response(302, headers={"Location": "/pic?Signature=second"}),
        response(body=PICTURE_BYTES, headers={"Content-Type": "image/png"}),
    ])
    with HikvisionClient(config()) as client:
        HikvisionPersons(client).get_picture(PersonPhoto(pic_uri=TEST_URI, server_index_code="test-server"))
    assert calls[1][1].url == "https://hik.example/artemis/api/resource/v1/person/photo?Signature=first"
    assert calls[2][1].url == "https://hik.example/pic?Signature=second"


@pytest.mark.parametrize("location", ["https://unrelated.example/pic", "https://user:pass@hik.example/pic", "file:///tmp/pic"])
def test_unapproved_picture_targets_are_rejected_before_get(transport, location):
    replies, calls = transport
    replies.append(response(302, headers={"Location": location}))
    with HikvisionClient(config()) as client, pytest.raises(HikvisionError, match="not an allowed"):
        HikvisionPersons(client).get_picture(PersonPhoto(pic_uri=TEST_URI, server_index_code="test-server"))
    assert len(calls) == 1


def test_separate_picture_server_can_be_explicitly_allowed(transport):
    replies, _ = transport
    replies.extend([
        response(302, headers={"Location": "https://storage.example:6114/pic"}),
        response(body=PICTURE_BYTES, headers={"Content-Type": "image/jpeg"}),
    ])
    with HikvisionClient(config(picture_hosts=("storage.example",))) as client:
        picture = HikvisionPersons(client).get_picture(PersonPhoto(pic_uri=TEST_URI, server_index_code="test-server"))
    assert picture.content == PICTURE_BYTES


@pytest.mark.parametrize("status,payload,expected_code", [
    (404, {"message": "Not Found"}, None),
    (200, {"code": "denied", "msg": "API permission denied"}, "denied"),
    (500, {"ErrorCode": "12724", "Message": "digest check fail or query expired or date wrong."}, "12724"),
])
def test_http_and_business_errors_retain_status_and_code(transport, status, payload, expected_code):
    replies, _ = transport
    replies.append(response(status, payload=payload))
    with HikvisionClient(config()) as client, pytest.raises(HikvisionError) as caught:
        client.post_json(PERSON_LIST_PATH, {"pageNo": 1, "pageSize": 10})
    assert caught.value.status_code == status
    assert caught.value.code == expected_code


def test_error_logs_redact_credentials_and_picture_details(transport, caplog):
    replies, _ = transport
    message = f"failed: {TEST_KEY} {TEST_SECRET} {TEST_URI} test-picture-server"
    replies.append(response(403, payload={"code": "denied", "msg": message}))
    with caplog.at_level(logging.WARNING), HikvisionClient(config()) as client, pytest.raises(HikvisionError) as caught:
        HikvisionPersons(client).get_picture(PersonPhoto.model_validate(TEST_PERSON["personPhoto"]))
    for value in (TEST_KEY, TEST_SECRET, TEST_URI, "test-picture-server"):
        assert value not in str(caught.value) + caplog.text


def test_transport_exception_does_not_leak_signed_url(transport, caplog):
    replies, _ = transport
    replies.extend([
        response(302, headers={"Location": "https://hik.example/pic?Signature=test-private-signature"}),
        requests.Timeout("https://hik.example/pic?Signature=test-private-signature"),
    ])
    with caplog.at_level(logging.WARNING), HikvisionClient(config()) as client, pytest.raises(HikvisionError) as caught:
        HikvisionPersons(client).get_picture(PersonPhoto(pic_uri=TEST_URI, server_index_code="test-server"))
    assert "Timeout" in str(caught.value)
    assert "test-private-signature" not in str(caught.value) + caplog.text
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("bad_response", [
    response(302, headers={}, body=b""),
    response(body=b"<html>Login</html>", headers={"Content-Type": "text/html"}),
    response(body=b"", headers={"Content-Type": "image/jpeg"}),
])
def test_missing_location_html_and_empty_images_are_rejected(transport, bad_response):
    replies, _ = transport
    replies.append(bad_response)
    with HikvisionClient(config()) as client, pytest.raises(HikvisionError):
        HikvisionPersons(client).get_picture(PersonPhoto(pic_uri=TEST_URI, server_index_code="test-server"))


def test_picture_redirect_loop_is_bounded(transport):
    replies, calls = transport
    replies.extend(response(302, headers={"Location": "/pic"}) for _ in range(3))
    with HikvisionClient(config(max_picture_redirects=2)) as client, pytest.raises(HikvisionError, match="limit"):
        HikvisionPersons(client).get_picture(PersonPhoto(pic_uri=TEST_URI, server_index_code="test-server"))
    assert len(calls) == 3


def test_size_limit_and_response_cleanup(transport, monkeypatch):
    replies, _ = transport
    too_large = response(body=b"x" * 20, headers={"Content-Type": "image/jpeg"})
    closed = []
    monkeypatch.setattr(too_large, "close", lambda: closed.append(True))
    replies.append(too_large)
    with HikvisionClient(config(max_response_bytes=10)) as client, pytest.raises(HikvisionError, match="size limit"):
        client.post(PERSON_PICTURE_PATH, {})
    assert closed == [True]


@pytest.mark.parametrize("data", [None, {}, {"total": 1, "pageNo": 1, "pageSize": 10, "list": [{}]}])
def test_malformed_person_list_is_a_connector_error(transport, data):
    replies, _ = transport
    replies.append(response(payload={"code": "0", "data": data}))
    with HikvisionClient(config()) as client, pytest.raises(HikvisionError, match="Invalid personList"):
        HikvisionPersons(client).list_persons()


def test_null_photo_and_no_photo_are_supported(transport):
    replies, _ = transport
    replies.extend(response(payload={"code": "0", "data": data}) for data in (
        {"personId": "test-person", "personPhoto": None}, {"personId": "test-person"},
    ))
    with HikvisionClient(config()) as client:
        assert HikvisionPersons(client).get_person("test-person").person_photo is None
        assert HikvisionPersons(client).get_person("test-person").person_photo is None


def test_invalid_input_and_closed_client_do_not_make_requests(transport):
    _, calls = transport
    with HikvisionClient(config()) as client:
        persons = HikvisionPersons(client)
        with pytest.raises(ValueError):
            persons.list_persons(page_no=True)
        with pytest.raises(ValueError):
            persons.get_person(" ")
        with pytest.raises(ValueError):
            persons.get_picture(PersonPhoto(pic_uri=TEST_URI))
        with pytest.raises(ValueError):
            client.post("https://unrelated.example/api", {})
    with pytest.raises(HikvisionError, match="closed"):
        persons.list_persons()
    assert calls == []


def test_connector_import_does_not_initialize_database_or_inference():
    script = (
        "import sys; import AiVision.connectors.hikvision; "
        "assert not any(name in sys.modules for name in "
        "('AiVision.core.settings', 'AiVision.core.db', 'sqlalchemy', 'cv2', 'insightface')); "
        "assert not any(name.startswith('AiVision.features.') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[2], check=True)
