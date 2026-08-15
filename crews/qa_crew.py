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
            "围绕核心链路（排班→对话→提炼→评估→审阅→成长曲线）编写并运行"
            "单元/集成/端到端测试，产出通过/不通过结论与缺陷清单"
        ),
        backstory=(
            "你是一名测试工程师，擅长设计覆盖关键路径与边界情况的用例，"
            "并以可复现的方式给出测试结论。"
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
            "找出隐患并给出可执行的改进建议。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    test_task = Task(
        description=(
            "对已实现的鸭鸭日记本应用编写并运行测试，覆盖核心链路与边界，"
            "输出测试报告（通过/不通过 + 缺陷清单）。"
        ),
        expected_output="测试报告（结论 + 缺陷清单）。",
        agent=tester,
    )

    review_task = Task(
        description=(
            "审查后端与前端代码，对照 API 契约检查一致性，"
            "输出代码审查意见（问题分级 + 建议）。"
        ),
        expected_output="代码审查意见。",
        agent=reviewer, context=[test_task],
    )

    return Crew(
        agents=[tester, reviewer],
        tasks=[test_task, review_task],
        process=Process.sequential,
        verbose=True,
    )
