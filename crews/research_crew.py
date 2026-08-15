"""示例 Crew：研究员 -> 撰稿人（顺序协作）。

可作为模板扩展：新增 Agent / Task 时，在 build_crew() 中按同样方式组织即可。
"""
from crewai import Agent, Crew, Process, Task

from config.llm import get_deepseek_llm


def build_crew() -> Crew:
    llm = get_deepseek_llm()

    researcher = Agent(
        role="资深研究员",
        goal="围绕「{topic}」找出最重要的 3 个趋势并说明理由",
        backstory=(
            "你是一名严谨的研究员，擅长从海量信息中提炼关键洞察，"
            "结论简洁、有依据。"
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    writer = Agent(
        role="内容撰稿人",
        goal="把研究结论写成一篇通俗易懂的中文短文",
        backstory=(
            "你是一名资深科技作者，擅长把复杂概念讲得清晰生动，"
            "语言流畅、结构分明。"
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    research_task = Task(
        description="围绕「{topic}」找出最重要的 3 个趋势，每个趋势附一句话理由。",
        expected_output="3 个趋势，每个趋势含一句话说明。",
        agent=researcher,
    )

    write_task = Task(
        description="基于研究员的 3 个趋势结论，写一篇约 300 字的中文短文。",
        expected_output="一篇结构清晰、约 300 字的中文短文。",
        agent=writer,
    )

    return Crew(
        agents=[researcher, writer],
        tasks=[research_task, write_task],
        process=Process.sequential,
        verbose=True,
    )
