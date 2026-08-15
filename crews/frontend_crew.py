"""前端 Crew：幼儿端工程师 ∥ 教师端工程师（并行，靠 API 契约解耦）。

产出：React + Tailwind 的幼儿端与教师端页面。
"""
from crewai import Agent, Crew, Process, Task

from config.llm import get_deepseek_llm


def build_crew() -> Crew:
    llm = get_deepseek_llm()

    child_fe = Agent(
        role="前端工程师（幼儿端）",
        goal=(
            "实现幼儿端页面：按住说话(PTT) 语音对话、开场/过程/结束动画、"
            "大字号大按钮高对比、投影友好"
        ),
        backstory=(
            "你是一名擅长儿童交互的前端工程师，精通 React 与 CSS 动画，"
            "能把语音与动画体验做得直观、有趣、响应迅速。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    teacher_fe = Agent(
        role="前端工程师（教师端）",
        goal=(
            "实现教师端页面：班级管理、排班、值日审阅（提炼修正+评估确认）、"
            "能力成长曲线、明细检索"
        ),
        backstory=(
            "你是一名擅长数据后台的前端工程师，注重信息密度与操作效率，"
            "能做出清晰、专业、数据完整的教师工作台。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    child_task = Task(
        description=(
            "实现幼儿端：PTT 语音采集（浏览器 Web Speech API）、对话流、"
            "鸭鸭日记本动画与语音播报、投影友好的大字号布局。"
        ),
        expected_output="幼儿端前端代码（React + Tailwind）。",
        agent=child_fe,
    )

    teacher_task = Task(
        description=(
            "实现教师端：幼儿/小鸭/排班管理、值日审阅（可修正提炼与评估并确认）、"
            "能力成长曲线图表、对话明细与流水检索。"
        ),
        expected_output="教师端前端代码（React + Tailwind）。",
        agent=teacher_fe,
    )

    return Crew(
        agents=[child_fe, teacher_fe],
        tasks=[child_task, teacher_task],
        process=Process.sequential,  # 两个 task 无强依赖，可视为并行分工
        verbose=True,
    )
