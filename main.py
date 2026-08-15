"""鸭鸭日记本研发流水线入口。

用法：
    python main.py            # 运行完整研发流水线（设计 → 开发 → 测试 → 验收）
    python main.py --plot     # 输出 Flow 拓扑图
"""
import sys


def main() -> None:
    from flows.delivery_flow import DeliveryFlow

    flow = DeliveryFlow()

    if "--plot" in sys.argv:
        flow.plot("delivery_flow")
        print("拓扑图已生成：delivery_flow.html")
        return

    print("=" * 56)
    print("鸭鸭日记本 · CrewAI 研发流水线启动")
    print("=" * 56)
    result = flow.kickoff()
    print("\n最终结果：", result)


if __name__ == "__main__":
    main()
