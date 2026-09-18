"""Create courseware-based multiple-choice quizzes for each training batch."""
from __future__ import annotations

import json
from random import Random
from sqlalchemy import select

from ..core.db import SessionLocal
from ..models import DevelopmentTrainingTask, DevelopmentTrainingWeek


def choice(prompt: str, options: list[str], answer: str, explanation: str) -> dict[str, object]:
    return {"type": "choice", "prompt": prompt, "options": options, "answer": answer, "explanation": explanation}


def finance_questions() -> list[dict[str, object]]:
    return [
        choice("资产负债表主要反映什么？", ["特定时点的资产、负债和权益", "一段期间的收入和费用", "现金流量的分类", "系统访问日志"], "特定时点的资产、负债和权益", "资产负债表反映某一时点的财务状况；收入和费用属于利润表的期间信息。"),
        choice("收入接口漏传销售数据，最直接可能影响哪项认定？", ["收入完整性", "固定资产存在", "银行账户权限", "备份可恢复性"], "收入完整性", "销售数据没有完整进入收入系统或总账，会造成应确认的收入遗漏。"),
        choice("一笔赊销确认收入时，通常同时增加什么？", ["应收账款", "库存数量", "银行存款", "固定资产"], "应收账款", "赊销已形成收入但尚未收款，因此通常形成应收账款而非立即增加现金。"),
        choice("判断系统是否应纳入审计范围，最重要的依据是什么？", ["是否处理可能影响重大科目或认定的数据", "系统名称是否含 ERP", "使用人数是否最多", "页面是否复杂"], "是否处理可能影响重大科目或认定的数据", "Scope 的判断取决于系统对财务报告风险和财审依赖的影响，而不是系统名称或界面。"),
        choice("从业务事件追到财务结果时，合理的链路是什么？", ["业务事件→系统处理→会计结果→科目和认定", "系统截图→底稿格式→项目排期→结论", "用户权限→办公地点→预算→报表", "备份日志→代码版本→访谈纪要→收入"], "业务事件→系统处理→会计结果→科目和认定", "该链路能够把系统异常解释为具体的财务报告影响。"),
        choice("利润增加但现金未立即增加，最常见的业务原因是什么？", ["形成了应收账款", "系统已完成备份", "用户已完成权限复核", "程序未发生变更"], "形成了应收账款", "赊销确认收入会增加利润和应收；现金要在客户付款后才增加。"),
    ]


def itgc_questions() -> list[dict[str, object]]:
    return [
        choice("用户新增、权限变更、离职停用和高权限复核主要属于 C22 的哪个领域？", ["信息安全（SA）", "运行维护（PE）", "变更管理（PM）", "系统开发（NS）"], "信息安全（SA）", "SA 覆盖账号生命周期、权限授权与复核，以及高权限访问的可追溯性。"),
        choice("备份任务显示成功，尚不能直接证明什么？", ["备份文件能够按要求恢复", "备份任务已执行", "存在备份日志", "系统配置了备份策略"], "备份文件能够按要求恢复", "备份成功只证明任务运行；恢复测试才验证数据、配置和应用能否真正恢复。"),
        choice("程序变更最完整的受控证据链是哪一组？", ["需求、测试、审批、生产部署记录", "开发人员口头说明和截图", "生产环境结果截图", "变更后的源代码"], "需求、测试、审批、生产部署记录", "完整证据链说明变更有业务原因、经过测试和授权，并可追溯至生产发布。"),
        choice("仅核对期末用户清单的主要局限是什么？", ["无法证明全年权限生命周期控制是否有效", "无法看到用户姓名", "无法导出文件", "无法取得系统截图"], "无法证明全年权限生命周期控制是否有效", "期末状态正常不代表离职停用、权限变更和定期复核在整个期间及时执行。"),
        choice("接口或批处理失败后，哪项做法最能降低财务数据遗漏风险？", ["监控失败、处理异常并完成结果核对", "只重启服务器", "删除失败日志", "等待下月再处理"], "监控失败、处理异常并完成结果核对", "失败处理必须形成闭环，确认应传输的数据已完整、准确地进入目标系统。"),
        choice("紧急变更缺少常规事前审批时，首先应继续确认什么？", ["紧急性依据、必要授权、事后复核和生产操作留痕", "开发人员的工龄", "系统页面颜色", "本月预算"], "紧急性依据、必要授权、事后复核和生产操作留痕", "紧急变更并非必然失控，关键在于例外流程是否保留授权、可追溯性和及时复核。"),
    ]


def itac_questions() -> list[dict[str, object]]:
    return [
        choice("测试自动控制时，除观察一次运行结果外，还应关注什么？", ["控制逻辑、参数维护、期间变更和实际输入输出", "系统界面颜色", "用户个人偏好", "报表打印格式"], "控制逻辑、参数维护、期间变更和实际输入输出", "一次演示不能证明自动控制持续有效；还要验证逻辑、参数和期间内变更是否受控。"),
        choice("系统间接口测试通常应分别评价哪两项？", ["完整性和准确性", "速度和页面美观", "人员数量和办公地点", "预算和工时"], "完整性和准确性", "接口需要既不漏传或重复传输，也不能把错误字段、金额或状态传入目标系统。"),
        choice("系统生成并被人工控制或审计程序使用的信息称为什么？", ["IPE", "SA", "RPO", "PBC"], "IPE", "IPE 是系统生成信息；使用它时需评价来源、逻辑、参数和总体完整性。"),
        choice("使用系统报表作为审计证据时，应首先确认什么？", ["来源、参数、生成逻辑和总体范围", "报表是否彩色打印", "文件大小", "导出人员工龄"], "来源、参数、生成逻辑和总体范围", "金额合计相等不足以证明筛选条件、字段口径或总体没有遗漏。"),
        choice("接口失败后仅执行重传、不核对结果，最可能留下什么风险？", ["重复或遗漏的数据未被发现", "系统界面无法登录", "备份文件变大", "密码会立即过期"], "重复或遗漏的数据未被发现", "重传本身不能证明目标系统结果正确，需要与源数据或控制总额进行核对。"),
        choice("自动控制在期间内持续可靠的重要前提之一是什么？", ["相关程序和关键参数受到变更管理控制", "报表使用统一字体", "每位用户都能修改参数", "只保留期末截图"], "相关程序和关键参数受到变更管理控制", "程序逻辑或参数未经控制地修改，可能改变自动控制结果并削弱期间依赖。"),
    ]


def data_questions() -> list[dict[str, object]]:
    return [
        choice("开始 CAATs 分析前，首要步骤是什么？", ["明确审计问题、总体、期间、字段和业务口径", "先生成复杂代码", "先挑选异常结果", "先写审计结论"], "明确审计问题、总体、期间、字段和业务口径", "审计问题决定数据范围与规则；没有口径的代码即使运行成功也可能得出错误结论。"),
        choice("两个数据表按姓名关联后异常数量激增，最应先检查什么？", ["主键、同名、账号复用和关联关系", "图表颜色", "文件扩展名", "输出页码"], "主键、同名、账号复用和关联关系", "姓名通常不是可靠主键；错误关联会放大记录并制造并不存在的异常。"),
        choice("可复现的分析结果至少应保留什么？", ["输入版本、代码或规则、参数、运行记录和结果索引", "仅最终截图", "仅异常清单", "仅口头说明"], "输入版本、代码或规则、参数、运行记录和结果索引", "复核人需要能够确认使用了哪份数据、何种规则，并重新得到相同结果。"),
        choice("异常记录应如何支持后续审计核验？", ["通过业务主键追溯回原始记录", "只保留汇总金额", "删除正常记录", "只保留图表"], "通过业务主键追溯回原始记录", "异常必须能追至源单据或系统交易，才能验证事实、取得解释并形成结论。"),
        choice("代码运行无报错但审计结论错误，最可能的原因是什么？", ["数据口径、关联逻辑或审计前提错误", "电脑性能不足", "字体不统一", "浏览器缓存"], "数据口径、关联逻辑或审计前提错误", "技术上可执行不等于审计上正确；总体、字段和规则必须与审计目标一致。"),
        choice("AI 或脚本输出异常后，下一步应是什么？", ["核对总体、规则和原始记录，再判断异常含义", "直接定性为控制无效", "立即删除异常", "只修改输出格式"], "核对总体、规则和原始记录，再判断异常含义", "分析命中只是线索，仍需确认数据质量、业务解释和证据边界。"),
    ]


def quality_questions() -> list[dict[str, object]]:
    return [
        choice("收到一条底稿 Review 意见后，正确的后续动作是什么？", ["分析根因并横向检查同类底稿", "只修改被标记单元格", "删除 Review 记录", "等待下次项目再处理"], "分析根因并横向检查同类底稿", "同类问题常在多个底稿中重复出现，横向扫描才能把一次意见沉淀为质量规则。"),
        choice("底稿结论可以写为“控制有效”的前提是什么？", ["测试范围、证据和例外能够支持该结论", "取得一张系统截图", "项目负责人未提出意见", "底稿格式完整"], "测试范围、证据和例外能够支持该结论", "结论必须与总体、期间、样本、证据和例外评价保持一致。"),
        choice("金额合计一致仍不足以证明系统报表的哪项可靠性？", ["筛选条件和字段口径正确", "报表有标题", "文件可以打开", "页面可以打印"], "筛选条件和字段口径正确", "报表可能金额相等但遗漏记录、选错期间或使用错误字段，因此仍要测试来源与逻辑。"),
        choice("发现控制例外后，第一步应是什么？", ["确认事实、范围和是否存在补偿控制", "立即写控制无效", "忽略单个例外", "删除异常数据"], "确认事实、范围和是否存在补偿控制", "例外需要先确认是否真实、是否孤立、影响范围多大，以及是否有其他控制降低风险。"),
        choice("仅给出审计目标、没有历史模板时，首先应设计什么？", ["风险、控制目标、资料、程序和证据标准", "底稿字体和页码", "项目预算", "系统界面配色"], "风险、控制目标、资料、程序和证据标准", "先建立测试逻辑，才能确定需要什么资料、如何选择样本及结论能够支持到什么程度。"),
        choice("一份可复核的底稿最重要的特征是什么？", ["他人能沿引用路径理解事实、程序、证据和结论", "文字越多越好", "只保留最终结论", "不记录例外事项"], "他人能沿引用路径理解事实、程序、证据和结论", "可复核性要求推理过程和证据路径清晰，而不只是结论写得简短或篇幅很长。"),
    ]


def _shuffle_question_options(questions: list[dict[str, object]], seed: str) -> list[dict[str, object]]:
    """Randomize distractors while balancing answer positions within each assignment."""
    randomized: list[dict[str, object]] = []
    positions = [0, 1, 2, 3]
    Random(f"{seed}:positions").shuffle(positions)
    for index, question in enumerate(questions):
        item = dict(question)
        options = list(item.get("options") or [])
        answer = item.get("answer")
        Random(f"{seed}:{index}").shuffle(options)
        if answer in options and len(options) >= 4:
            target = positions[index % len(positions)]
            current = options.index(answer)
            options[current], options[target] = options[target], options[current]
        item["options"] = options
        randomized.append(item)
    return randomized


def _courseware_topic(task: DevelopmentTrainingTask, week: DevelopmentTrainingWeek) -> str:
    text = f"{week.title} {week.objective} {task.title} {task.description} {task.purpose}".lower()
    if any(key in text for key in ("itac", "ipe", "interface", "接口", "自动控制", "自动计算")):
        return "itac"
    if any(key in text for key in ("itgc", "权限", "技术地图", "备份", "日志", "sa/pm/ns", "系统取证", "访问管理", "变更")):
        return "itgc"
    if any(key in text for key in ("caats", "代码", "数据", "sql", "交叉验证", "审计化", "数据技术")):
        return "data"
    if any(key in text for key in ("业务", "财审", "会计", "制造", "收入", "三大报表", "科目", "存货", "采购", "销售")):
        return "finance"
    return "quality"


def _task_context_question(task: DevelopmentTrainingTask, topic: str) -> dict[str, object]:
    title = task.title.strip() or "本节任务"
    common = {
        "itac": ("先明确风险和控制目标，再追踪输入、控制逻辑、参数、输出与例外处理", "直接查看一张正常结果截图", "只询问系统管理员控制是否存在", "只核对期末报表金额"),
        "itgc": ("先界定控制目标和适用期间，再取得总体、样本、审批或运行证据并评价例外", "只确认期末系统可以登录", "只保留管理层口头说明", "只查看一张无日期的系统截图"),
        "data": ("先明确总体、期间、字段口径和关联规则，再运行分析并追溯异常", "先挑选看起来异常的记录，再补充分析目的", "只保存最终图表，不保留数据和规则", "代码无报错后直接形成审计结论"),
        "finance": ("从业务单据追至系统处理和会计结果，再反向验证关键认定", "只核对总账金额是否相等", "只复述访谈得到的流程", "先写结论，再寻找支持资料"),
        "quality": ("先界定风险、程序、证据和结论边界，再形成可回溯的工作记录", "先套用历史底稿文字", "只修改被指出的格式问题", "以资料数量代替证据评价"),
    }
    correct, *wrong = common[topic]
    return choice(
        f"围绕“{title}”完成本节任务时，最符合课件要求的起步方式是什么？",
        [correct, *wrong], correct,
        f"本节“{title}”要求把任务要求落实为风险、程序、证据和结论的完整链路；先完成这一拆解，后续的取证和判断才有明确方向。",
    )


def _contextualize_questions(task: DevelopmentTrainingTask, questions: list[dict[str, object]], topic: str) -> list[dict[str, object]]:
    """Keep knowledge checks tied to the learner's current courseware and task."""
    title = task.title.strip() or "本节任务"
    contextualized = [_task_context_question(task, topic)]
    for question in questions[:5]:
        item = dict(question)
        item["prompt"] = f"在“{title}”这一节的学习情境中，{item['prompt']}"
        item["explanation"] = f"结合本节“{title}”：{item['explanation']}"
        contextualized.append(item)
    return contextualized


def questions_for(task: DevelopmentTrainingTask, week: DevelopmentTrainingWeek) -> list[dict[str, object]]:
    topic = _courseware_topic(task, week)
    bank = {
        "data": data_questions,
        "itac": itac_questions,
        "itgc": itgc_questions,
        "finance": finance_questions,
        "quality": quality_questions,
    }[topic]()
    return _shuffle_question_options(_contextualize_questions(task, bank, topic), f"{week.id}:{task.id}")


def refresh() -> int:
    with SessionLocal() as db:
        tasks = db.execute(select(DevelopmentTrainingTask).where(DevelopmentTrainingTask.submission_required == True)).scalars().all()  # noqa: E712
        for task in tasks:
            week = db.get(DevelopmentTrainingWeek, task.training_week_id)
            if week is None:
                continue
            task.self_check_questions = json.dumps(questions_for(task, week), ensure_ascii=False)
        db.commit()
        return len(tasks)


if __name__ == "__main__":
    print(f"updated {refresh()} training assignments")
