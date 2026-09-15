"""
功能模块共享基础设施。

负责：
    配置怎么读
    数据库配置基类
    Consumer怎么启动
    怎么取帧
    怎么送模型推理
    怎么处理ROI
    怎么停止线程

1、spec: 一个检测功能应该声明哪些东西
2、orm.py: 功能配置数据库的共同结构
3、config_manager.py: 功能配置怎么查询
4、consumer.py : 所有检测功能真正运行的公共主流程
5、tracking.py : 跟踪相关公关能力
6、dwell_consumer.py : 人员逗留检测的公共业务层
"""
