export const workflowUsers = [
  {id: 'u01', name: '李睿', role: '项目现场负责人', phone: '13800010001', email: 'lirui@example.com'},
  {id: 'u02', name: '王经理', role: '项目负责经理', phone: '13800010002', email: 'manager@example.com'},
  {id: 'u03', name: '陈复核', role: '质控复核人', phone: '13800010003', email: 'reviewer@example.com'},
  {id: 'u04', name: '赵助理', role: 'IT审计助理', phone: '13800010004', email: 'assistant@example.com'},
  {id: 'u05', name: '刘顾问', role: 'ITAC测试成员', phone: '13800010005', email: 'itac@example.com'},
];

export const workflowProjects = [
  {
    id: 'p-zjdw',
    name: '浙江德威2025年IT审计',
    shortName: '浙江德威',
    client: '浙江德威科技有限公司',
    auditYear: 2025,
    auditScope: '2025-01-01 至 2025-12-31',
    auditScopeSource: '从项目计划与底稿首页识别，需复核确认',
    stage: '项目实施',
    status: '进行中',
    progress: 68,
    materialRate: 76,
    workpaperRate: 62,
    checkPassRate: 71,
    dueDays: 12,
    riskLevel: '中',
    leader: '王经理',
    manager: '王经理',
    qualityReviewer: '陈复核',
    fieldLead: '李睿',
    members: ['李睿', '赵助理', '刘顾问'],
    firstPartner: '财审一签-周合伙人',
    secondPartner: '财审二签-钱合伙人',
    startDate: '2026-06-15',
    endDate: '2026-07-12',
    systems: ['sys-gerp', 'sys-ihr', 'sys-hfm', 'sys-kssp', 'sys-db'],
    nextActions: ['补充特权账号审阅证据', '复核C21-1问题清单', '确认B类底稿编制人与复核人'],
  },
  {
    id: 'p-company-t',
    name: '公司T信息系统独立性隔离审计',
    shortName: '公司T隔离',
    client: '公司T',
    auditYear: 2025,
    auditScope: '2025-01-01 至 2025-12-31',
    auditScopeSource: '从访谈纪要和系统清单初步识别',
    stage: '项目准备',
    status: '进行中',
    progress: 41,
    materialRate: 58,
    workpaperRate: 33,
    checkPassRate: 64,
    dueDays: 26,
    riskLevel: '高',
    leader: '王经理',
    manager: '王经理',
    qualityReviewer: '陈复核',
    fieldLead: '赵助理',
    members: ['赵助理', '刘顾问'],
    firstPartner: '财审一签-孙合伙人',
    secondPartner: '财审二签-吴经理',
    startDate: '2026-06-24',
    endDate: '2026-07-25',
    systems: ['sys-oa', 'sys-kd', 'sys-db'],
    nextActions: ['补齐系统边界说明', '获取管理员清单', '确认隔离控制测试样本'],
  },
  {
    id: 'p-health',
    name: '大健康系统建设后评价',
    shortName: '大健康后评价',
    client: '大健康集团',
    auditYear: 2025,
    auditScope: '2025-01-01 至 2025-12-31',
    auditScopeSource: '默认年度范围，等待项目经理确认',
    stage: '复核整改',
    status: '待处理',
    progress: 82,
    materialRate: 89,
    workpaperRate: 78,
    checkPassRate: 83,
    dueDays: 6,
    riskLevel: '中',
    leader: '李睿',
    manager: '王经理',
    qualityReviewer: '陈复核',
    fieldLead: '李睿',
    members: ['李睿', '赵助理'],
    firstPartner: '财审一签-郑合伙人',
    secondPartner: '财审二签-冯经理',
    startDate: '2026-06-05',
    endDate: '2026-07-05',
    systems: ['sys-mes', 'sys-oa', 'sys-kd'],
    nextActions: ['处理A14-3复核退回', '关闭日志审阅问题', '更新质量看板风险评级'],
  },
];

export const workflowSystems = [
  {id: 'sys-gerp', name: 'G-ERP', owner: '财务共享中心', process: '总账、采购、销售、付款', inScope: true, reason: '承载财务报表关键流程', confidence: 92, risk: '中', dataSensitivity: '财务主数据', dependencies: '数据库平台 / HFM'},
  {id: 'sys-ihr', name: 'iHR', owner: '人力资源部', process: '员工、岗位、离职流程', inScope: true, reason: '影响权限开通和离职账号禁用', confidence: 86, risk: '中', dataSensitivity: '人员身份数据', dependencies: 'OA / AD'},
  {id: 'sys-hfm', name: 'HFM', owner: '财务报表组', process: '合并报表', inScope: true, reason: '合并报表关键系统', confidence: 90, risk: '高', dataSensitivity: '合并报表数据', dependencies: 'G-ERP'},
  {id: 'sys-kssp', name: 'KSSP', owner: '共享服务中心', process: '费用报销、审批流', inScope: true, reason: '自动生成费用与付款审批', confidence: 82, risk: '中', dataSensitivity: '报销单据', dependencies: 'OA / G-ERP'},
  {id: 'sys-db', name: '数据库平台', owner: 'IT基础架构部', process: '数据库运维与备份', inScope: true, reason: '支持多个关键业务系统', confidence: 78, risk: '高', dataSensitivity: '底层数据', dependencies: '备份平台'},
  {id: 'sys-mes', name: 'MES', owner: '制造运营部', process: '生产执行、工单、物料追踪', inScope: true, reason: '影响存货与成本核算完整性', confidence: 74, risk: '中', dataSensitivity: '生产订单', dependencies: '金蝶云星空'},
  {id: 'sys-kd', name: '金蝶云星空', owner: '财务信息化部', process: '总账、供应链、固定资产', inScope: true, reason: '财务核算主系统', confidence: 88, risk: '中', dataSensitivity: '财务凭证', dependencies: 'OA / 数据库平台'},
  {id: 'sys-oa', name: 'OA', owner: '集团办公室', process: '审批流、主数据申请', inScope: true, reason: '承载变更和权限审批证据', confidence: 80, risk: '低', dataSensitivity: '审批记录', dependencies: 'AD'},
];

export const workflowPbcRequests = [
  {id: 'pbc-01', projectId: 'p-zjdw', category: '权限管理', system: 'G-ERP', requirement: '2025年全年新增、变更、删除用户清单及审批记录', status: '已收到', due: '2026-06-22', owner: '赵助理', linked: 'C22 / B22A-4-4-1', gap: '缺少12月删除用户审批截图'},
  {id: 'pbc-02', projectId: 'p-zjdw', category: '权限管理', system: 'iHR', requirement: '离职人员清单与账号禁用记录', status: '待补充', due: '2026-06-30', owner: '客户IT-张工', linked: 'C22 / C21-1', gap: '离职人员与账号关闭日期未能匹配'},
  {id: 'pbc-03', projectId: 'p-zjdw', category: '变更管理', system: 'KSSP', requirement: '系统变更单、测试记录、上线审批', status: '部分收到', due: '2026-07-01', owner: '客户IT-王工', linked: 'B23 / A27-1', gap: '抽样变更缺少测试记录'},
  {id: 'pbc-04', projectId: 'p-zjdw', category: '运维管理', system: '数据库平台', requirement: '数据库备份策略、备份日志、恢复测试记录', status: '缺失', due: '2026-07-02', owner: '客户DBA', linked: 'C22 / B60-2-3', gap: '尚未提供恢复测试证据'},
  {id: 'pbc-05', projectId: 'p-company-t', category: '隔离控制', system: 'OA', requirement: 'IT与财务职责分离矩阵、审批角色说明', status: '待补充', due: '2026-07-05', owner: '客户内控', linked: 'C22 / C21', gap: '职责分离规则未形成清单'},
  {id: 'pbc-06', projectId: 'p-health', category: '日志管理', system: 'MES', requirement: '关键操作日志审阅记录和异常跟进记录', status: '部分收到', due: '2026-06-28', owner: 'MES管理员', linked: 'A14-3 / C21-1', gap: '3月、4月日志审阅记录缺失'},
];

export const workflowWorkpapers = [
  {id: 'wp-c22', projectId: 'p-zjdw', code: 'C22', name: '了解和评价信息技术一般控制', group: '2.项目实施', type: 'C类', status: '进行中', preparer: '李睿', reviewer: '王经理', evidenceNeeded: 18, evidenceReady: 13, autoFillFields: ['客户名称', '审计范围', '系统清单', '访谈对象'], findings: 3, returnCount: 1, attachments: ['访谈纪要', '系统清单', '权限清单']},
  {id: 'wp-c21-1', projectId: 'p-zjdw', code: 'C21-1', name: 'IT审计问题发现清单', group: '3.项目交付', type: 'C类', status: '有问题', preparer: '李睿', reviewer: '王经理', evidenceNeeded: 8, evidenceReady: 6, autoFillFields: ['问题类型', '涉及系统', '管理层反馈'], findings: 4, returnCount: 2, attachments: ['问题沟通表', '客户反馈邮件']},
  {id: 'wp-b22a', projectId: 'p-zjdw', code: 'B22A-4-4-1', name: '用户权限测试', group: '2.项目实施', type: 'B类', status: '进行中', preparer: '钱经理 / 李睿', reviewer: '财审一签-周合伙人', evidenceNeeded: 12, evidenceReady: 8, autoFillFields: ['样本编号', '审批证据索引', '测试结论'], findings: 2, returnCount: 0, attachments: ['新增用户清单', '审批截图']},
  {id: 'wp-b23', projectId: 'p-zjdw', code: 'B23', name: '变更管理测试', group: '2.项目实施', type: 'B类', status: '未开始', preparer: '钱经理 / 李睿', reviewer: '财审一签-周合伙人', evidenceNeeded: 10, evidenceReady: 4, autoFillFields: ['变更单号', '测试记录', '上线审批'], findings: 1, returnCount: 0, attachments: ['变更清单']},
  {id: 'wp-a27-1', projectId: 'p-zjdw', code: 'A27-1', name: '信息技术审计总结', group: '3.项目交付', type: 'A类', status: '待复核', preparer: '李睿', reviewer: '陈复核', evidenceNeeded: 7, evidenceReady: 5, autoFillFields: ['项目结论', '重要问题', '整改状态'], findings: 2, returnCount: 1, attachments: ['IT审计总结']},
  {id: 'wp-a14-3', projectId: 'p-zjdw', code: 'A14-3', name: '复核意见汇总', group: '3.项目交付', type: 'A类', status: '待处理', preparer: '李睿', reviewer: '陈复核', evidenceNeeded: 5, evidenceReady: 4, autoFillFields: ['复核意见', '整改说明', '关闭状态'], findings: 2, returnCount: 1, attachments: ['复核记录']},
  {id: 'wp-report', projectId: 'p-zjdw', code: 'RPT-IT', name: 'IT审计管理建议输出', group: '4.项目报告', type: '报告', status: '未开始', preparer: '李睿', reviewer: '王经理', evidenceNeeded: 4, evidenceReady: 1, autoFillFields: ['发现问题', '风险影响', '管理建议'], findings: 0, returnCount: 0, attachments: []},
  {id: 'wp-c22-t', projectId: 'p-company-t', code: 'C22', name: '了解和评价信息技术一般控制', group: '2.项目实施', type: 'C类', status: '进行中', preparer: '赵助理', reviewer: '王经理', evidenceNeeded: 16, evidenceReady: 7, autoFillFields: ['客户名称', '系统边界', '隔离控制'], findings: 2, returnCount: 0, attachments: ['系统访谈纪要']},
  {id: 'wp-c22-h', projectId: 'p-health', code: 'C22', name: '了解和评价信息技术一般控制', group: '2.项目实施', type: 'C类', status: '已完成', preparer: '李睿', reviewer: '王经理', evidenceNeeded: 17, evidenceReady: 16, autoFillFields: ['客户名称', '系统清单', '测试结论'], findings: 1, returnCount: 0, attachments: ['系统清单', '控制矩阵']},
];

export const workflowChecks = [
  {id: 'chk-01', projectId: 'p-zjdw', workpaperId: 'wp-c22', rule: 'C22-系统范围一致性', result: '未通过', severity: '高', finding: '底稿列示G-ERP、iHR、KSSP，但PBC资料新增HFM未同步纳入系统范围。', source: '系统', status: '待处理', locator: 'C22 / 系统范围表', evidence: '系统清单_v3.xlsx', recommendation: '确认HFM是否纳入审计范围，并同步更新C22和项目工作台。'},
  {id: 'chk-02', projectId: 'p-zjdw', workpaperId: 'wp-b22a', rule: 'B类编制复核人规则', result: '未通过', severity: '中', finding: 'B22A编制人应包含财审二签和IT现场负责人，当前仅显示IT现场负责人。', source: '系统', status: '已分派', locator: 'B22A / 表头', evidence: '底稿表头扫描', recommendation: '按规则补充财审二签为编制人，复核人保留财审一签。'},
  {id: 'chk-03', projectId: 'p-zjdw', workpaperId: 'wp-c21-1', rule: '问题清单闭环', result: '未通过', severity: '高', finding: '离职账号未禁用问题缺少管理层反馈和整改截止日期。', source: '人工', status: '待处理', locator: 'C21-1 / 问题2', evidence: '问题沟通表', recommendation: '补充整改责任人、预计完成日期和复核状态。'},
  {id: 'chk-04', projectId: 'p-zjdw', workpaperId: 'wp-b23', rule: '变更测试证据完整性', result: '未通过', severity: '中', finding: '抽样变更CHG-2025-112缺少测试记录。', source: '系统', status: '保留', locator: 'B23 / 样本4', evidence: '变更清单.xlsx', recommendation: '向客户补充测试记录或记录替代程序。'},
  {id: 'chk-05', projectId: 'p-zjdw', workpaperId: 'wp-a27-1', rule: '交付底稿一致性', result: '通过', severity: '低', finding: 'A27-1列示问题与C21-1一致。', source: '系统', status: '已关闭', locator: 'A27-1 / 问题汇总', evidence: 'C21-1读取结果', recommendation: '无需处理。'},
  {id: 'chk-06', projectId: 'p-company-t', workpaperId: 'wp-c22-t', rule: '职责分离矩阵完整性', result: '未通过', severity: '高', finding: '隔离审计项目尚未提供职责分离规则清单。', source: '系统', status: '待处理', locator: 'C22 / 隔离控制', evidence: 'PBC缺口', recommendation: '新增职责分离规则清单PBC并由经理确认范围。'},
  {id: 'chk-07', projectId: 'p-health', workpaperId: 'wp-c22-h', rule: '日志审阅记录连续性', result: '未通过', severity: '中', finding: 'MES 3月、4月日志审阅记录缺失。', source: '人工', status: '已修订', locator: 'A14-3 / 复核意见3', evidence: '日志审阅记录包', recommendation: '补充说明并由复核人关闭。'},
];

export const workflowReviews = [
  {id: 'rev-01', projectId: 'p-zjdw', workpaperId: 'wp-c21-1', reviewer: '王经理', round: 2, status: '退回', owner: '李睿', due: '2026-06-30', comment: '问题影响描述过短，需说明对财务报表审计的影响，并补齐整改责任人。'},
  {id: 'rev-02', projectId: 'p-zjdw', workpaperId: 'wp-a27-1', reviewer: '陈复核', round: 1, status: '退回', owner: '李睿', due: '2026-07-01', comment: 'A27-1总结未体现权限、变更、备份三类控制缺陷的最终处理状态。'},
  {id: 'rev-03', projectId: 'p-zjdw', workpaperId: 'wp-b22a', reviewer: '王经理', round: 1, status: '待复核', owner: '赵助理', due: '2026-07-02', comment: '新增用户抽样底稿已提交，等待经理复核。'},
  {id: 'rev-04', projectId: 'p-health', workpaperId: 'wp-c22-h', reviewer: '陈复核', round: 2, status: '已关闭', owner: '李睿', due: '2026-06-26', comment: '系统范围与问题清单已一致，关闭。'},
];

export const workflowFindings = [
  {id: 'f-01', projectId: 'p-zjdw', title: '离职账号未及时禁用', source: '系统', severity: '高', status: '待处理', owner: '客户IT-张工', due: '2026-07-03', workpaper: 'C21-1 / C22', cause: 'iHR离职清单与G-ERP账号状态不一致', action: '补充禁用记录并确认是否存在越权操作', ageing: 5, qualityRisk: '影响权限管理控制有效性结论'},
  {id: 'f-02', projectId: 'p-zjdw', title: '权限新增审批证据不完整', source: '系统', severity: '中', status: '已分派', owner: '赵助理', due: '2026-07-02', workpaper: 'B22A-4-4-1', cause: '12月样本缺少审批截图', action: '重新向客户索取审批记录', ageing: 3, qualityRisk: '影响样本测试可执行性'},
  {id: 'f-03', projectId: 'p-zjdw', title: '变更缺少测试记录', source: '系统', severity: '中', status: '保留', owner: '客户IT-王工', due: '2026-07-04', workpaper: 'B23', cause: 'CHG-2025-112未归档测试记录', action: '补充测试记录或执行替代程序', ageing: 4, qualityRisk: '影响变更管理控制结论'},
  {id: 'f-04', projectId: 'p-zjdw', title: 'B类底稿表头责任人不符合规则', source: '系统', severity: '中', status: '已修订', owner: '李睿', due: '2026-06-29', workpaper: 'B22A / B23', cause: '未带入财审二签', action: '按自动填写规则修正测试副本', ageing: 1, qualityRisk: '影响底稿规范性'},
  {id: 'f-05', projectId: 'p-company-t', title: '职责分离规则清单缺失', source: '人工', severity: '高', status: '待处理', owner: '客户内控', due: '2026-07-05', workpaper: 'C22', cause: '尚未形成隔离控制矩阵', action: '补充角色冲突矩阵和管理层确认', ageing: 2, qualityRisk: '影响隔离审计核心目标'},
  {id: 'f-06', projectId: 'p-health', title: '日志未定期审阅', source: '人工', severity: '中', status: '已关闭', owner: 'MES管理员', due: '2026-06-25', workpaper: 'A14-3 / C21-1', cause: '3月、4月审阅记录缺失', action: '补齐审阅说明和异常跟进记录', ageing: 7, qualityRisk: '影响运维控制有效性'},
  {id: 'f-07', projectId: 'p-health', title: '备份恢复测试缺失', source: '系统', severity: '高', status: '待复核', owner: '李睿', due: '2026-07-01', workpaper: 'C22 / B60-2-3', cause: '未能提供年度恢复演练记录', action: '执行替代访谈并记录管理层声明', ageing: 6, qualityRisk: '影响持续运营控制结论'},
];

export const workflowTemplates = [
  {name: 'ITGC标准底稿模板', version: '2026.06', changed: '新增A14-3复核意见结构'},
  {name: 'B类权限测试模板', version: '2026.06', changed: '强化财审二签与IT现场负责人双编制规则'},
  {name: 'C22设计执行有效性程序', version: '2026.05', changed: '补充资料清单生成字段'},
];

export const workflowStages = [
  {id: 'prepare', name: '1.项目准备', description: '客户建档、项目立项、范围初判、PBC清单初始化'},
  {id: 'execute', name: '2.项目实施', description: '资料收集、访谈、系统范围确认、B/C类底稿执行'},
  {id: 'deliver', name: '3.项目交付', description: 'C21-1、C21、A27-1、A14-3交付复核和问题闭环'},
  {id: 'report', name: '4.项目报告', description: '管理建议、质量风险汇总和最终归档'},
];

export function getWorkflowProject(projectId) {
  return workflowProjects.find(project => project.id === projectId) || workflowProjects[0];
}

export function getProjectSystems(projectId) {
  const project = getWorkflowProject(projectId);
  const ids = new Set(project.systems);
  return workflowSystems.filter(system => ids.has(system.id));
}

export function getProjectPbc(projectId) {
  return workflowPbcRequests.filter(row => row.projectId === projectId);
}

export function getProjectWorkpapers(projectId) {
  return workflowWorkpapers.filter(row => row.projectId === projectId);
}

export function getProjectChecks(projectId) {
  return workflowChecks.filter(row => row.projectId === projectId);
}

export function getProjectReviews(projectId) {
  return workflowReviews.filter(row => row.projectId === projectId);
}

export function getProjectFindings(projectId) {
  return workflowFindings.filter(row => row.projectId === projectId);
}

export function getWorkpaper(workpaperId) {
  return workflowWorkpapers.find(row => row.id === workpaperId) || workflowWorkpapers[0];
}
