"""设计 Crew：产品经理 → 交互设计师 → UI 设计师 → 系统架构师。

产出：PRD、交互稿、UI 规范、API 契约与数据模型。
"""
from crewai import Agent, Crew, Process, Task

from config.llm import get_deepseek_llm


def build_crew() -> Crew:
    llm = get_deepseek_llm()

    pm = Agent(
        role="产品经理",
        goal=(
            "把「鸭鸭日记本」需求规格拆解为可执行的 PRD 与可勾选的验收清单，"
            "明确幼儿端/教师端的功能边界、核心流程与成功标准"
        ),
        backstory=(
            "你是一名资深产品经理，擅长把模糊需求转化为清晰、可验收、可执行的产品文档，"
            "尤其关注目标用户（幼儿园教师与幼儿）的真实使用场景。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    ux = Agent(
        role="交互设计师",
        goal=(
            "为幼儿端与教师端设计页面流程、交互细节与对话脚本，"
            "确保幼儿端零学习成本、教师端操作不超过两步"
        ),
        backstory=(
            "你是一名专注儿童产品的交互设计师，深谙幼儿的认知特点，"
            "擅长用大按钮、大字号、语音与动画降低交互门槛。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    ui = Agent(
        role="UI 设计师",
        goal=(
            "定义设计令牌（色彩/字体/间距）与组件规范，输出幼儿端亮色投影风、"
            "教师端专业风的视觉稿说明"
        ),
        backstory=(
            "你是一名 UI 设计师，擅长为儿童产品做高对比、高饱和的友好视觉，"
            "同时能为教师后台做克制、信息密度高的专业界面。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    architect = Agent(
        role="系统架构师",
        goal=(
            "产出技术架构、数据模型、REST API 契约与目录结构，"
            "作为前后端并行开发解耦的「合同」"
        ),
        backstory=(
            "你是一名全栈架构师，精通 FastAPI + SQLAlchemy + SQLite 与 React，"
            "擅长用清晰的接口契约让前后端团队并行工作而不冲突。"
        ),
        llm=llm, verbose=True, allow_delegation=False,
    )

    pm_task = Task(
        description=(
            "基于以下需求规格，产出 PRD：功能清单（幼儿端/教师端/AI引擎/数据层）、"
            "核心流程、以及可勾选的验收清单。\n\n需求规格：\n{requirements}"
        ),
        expected_output="结构化 PRD 与验收清单（Markdown）。",
        agent=pm,
    )

    ux_task = Task(
        description=(
            "基于 PRD，设计幼儿端（PTT 语音对话、开场/过程/结束动画、投影友好）"
            "与教师端（管理/审阅/成长曲线/明细）的页面流程与交互细节，"
            "并给出幼儿对话脚本示例。"
        ),
        expected_output="交互设计说明（页面流转 + 交互细节 + 对话脚本）。",
        agent=ux, context=[pm_task],
    )

    ui_task = Task(
        description=(
            "基于交互设计，定义设计令牌（主色、辅助色、字体、间距、圆角）与组件规范，"
            "幼儿端亮色投影风、教师端专业风的视觉说明。"
        ),
        expected_output="UI 设计规范（设计令牌 + 组件规范 + 视觉说明）。",
        agent=ui, context=[ux_task],
    )

    arch_task = Task(
        description=(
            "基于 PRD 与交互设计，产出：技术架构、SQLite 数据模型（幼儿/小鸭/排班/会话/"
            "消息/流水/情绪/评估维度/评估/小鸭档案）、REST API 契约（路径/方法/入参/出参）"
            "与项目目录结构。"
        ),
        expected_output="架构文档 + 数据模型 + API 契约 + 目录结构（Markdown）。",
        agent=architect, context=[pm_task, ux_task],
    )

    return Crew(
        agents=[pm, ux, ui, architect],
        tasks=[pm_task, ux_task, ui_task, arch_task],
        process=Process.sequential,
        verbose=True,
    )
