"""测试 QA Crew：测试工程师 → 代码审查员。

产出：测试用例与测试报告、代码审查意见。
"""
from crewai import Agent, Crew, Process, Task

from config.llm import get_deepseek_llm


def build_crew() -> Crew:
    llm = get_deepseek_llm()

    tester = Agent(
        role="测试工程师",
        goal=(
            "产出测试方案说明与测试结论：围绕核心链路（排班→对话→提炼→评估→审阅→"
            "成长曲线）说明用例设计与验证结果"
        ),
        backstory=(
            "你是一名测试工程师，擅长设计覆盖关键路径与边界情况的用例，"
            "并以可复现的方式给出测试结论。你只输出文字，不直接运行测试。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    reviewer = Agent(
        role="代码审查员",
        goal=(
            "审查代码质量：与 API 契约的一致性、数据完整性、错误处理、"
            "安全与边界情况，产出审查意见"
        ),
        backstory=(
            "你是一名严格的代码审查员，能从可维护性、健壮性与安全性角度"
            "找出隐患并给出可执行的改进建议。你只输出文字，不修改代码。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    test_task = Task(
        description=(
            "产出测试方案说明与结论（文字）：核心链路（排班→对话→提炼→评估→审阅→"
            "成长曲线）的用例设计与覆盖点、边界情况。"
        ),
        expected_output="测试方案说明与结论（文字）。",
        agent=tester,
    )

    review_task = Task(
        description=(
            "产出代码审查意见（文字）：对照 API 契约检查一致性，"
            "输出问题分级与改进建议。"
        ),
        expected_output="代码审查意见（文字）。",
        agent=reviewer, context=[test_task],
    )

    return Crew(
        agents=[tester, reviewer],
        tasks=[test_task, review_task],
        process=Process.sequential,
        verbose=True,
    )
