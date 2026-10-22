"""人脸库自动更新的固定运维入口，不随功能包目录调整而改变。

默认依次同步人员资料、增量生成特征；部署和状态查询均不启动检测服务。
"""
from __future__ import annotations

import argparse
import importlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STAGE_MODULES = (
    ("人员资料同步", "AiVision.features.face_recognition.library.sync"),
    ("人脸特征生成", "AiVision.features.face_recognition.library.embedding"),
)


def check_entrypoints() -> None:
    """只校验实际业务入口可导入，不访问海康、数据库或加载模型。"""
    for stage, module_name in STAGE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            print(f"{stage}入口无法导入：{module_name}（{type(exc).__name__}）")
            raise
        if not callable(getattr(module, "main", None)):
            raise ValueError(f"{stage}缺少 main 入口")


def update_library() -> int:
    """保留每个来源和每个人员的独立提交，任何阶段失败均返回非零状态。"""
    failed = False
    for stage, module_name in STAGE_MODULES:
        print(f"[FaceLibraryUpdate] 开始{stage}", flush=True)
        try:
            result = importlib.import_module(module_name).main()
        except Exception as exc:
            # 底层异常可能带配置或数据库参数，不在统一入口输出原文。
            print(f"[FaceLibraryUpdate] {stage}异常：{type(exc).__name__}", flush=True)
            result = 1
        failed = failed or result != 0
        print(f"[FaceLibraryUpdate] {stage}{'完成' if result == 0 else '失败'}", flush=True)
        # 一个来源同步失败时，仍为其他来源已提交的人员生成特征。
    print(f"[FaceLibraryUpdate] 自动更新{'存在失败，请查看各来源统计' if failed else '全部完成'}", flush=True)
    return int(failed)


def main(argv: list[str] | None = None) -> int:
    """统一提供实际更新、入口校验、systemd 安装和只读状态查询。"""
    parser = argparse.ArgumentParser(description="海康人员及人脸特征自动更新")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true", help="仅校验业务入口，不连接外部服务")
    actions.add_argument("--install-systemd", action="store_true", help="安装或更新定时任务，并安排一次立即更新")
    actions.add_argument("--status", action="store_true", help="检查定时器、实际执行入口及最近执行结果")
    parser.add_argument("--dry-run", action="store_true", help="配合 --install-systemd 仅显示待安装的配置")
    args = parser.parse_args(argv)
    if args.dry_run and not args.install_systemd:
        parser.error("--dry-run 需要配合 --install-systemd")
    try:
        if args.status:
            from AiVision.features.face_recognition.library.automation import show_status

            return show_status(PROJECT_ROOT)
        if args.check or args.install_systemd:
            check_entrypoints()
            if args.check:
                print("人员同步与特征生成入口校验通过；未访问海康、数据库或加载模型。")
                return 0
            from AiVision.features.face_recognition.library.automation import install_systemd

            return install_systemd(PROJECT_ROOT, dry_run=args.dry_run)
        return update_library()
    except Exception as exc:
        print(f"[FaceLibraryUpdate] 运维操作失败：{type(exc).__name__}；请检查执行环境和 systemd 配置。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
