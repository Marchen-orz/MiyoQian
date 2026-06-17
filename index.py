import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from miyouqian.cli import main


def main_handler(event, context):
    print("====== 米游签云函数任务开始 ======")
    try:
        exit_code = main(["--config", "/path/to/your/config.json","run"])
        print(f"====== 任务执行完毕，退出码: {exit_code} ======")
        return None
    except Exception as e:
        print(f"====== 任务运行异常: {str(e)} ======")
        raise e
