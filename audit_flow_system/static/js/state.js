export const defaultModuleOrder = [
  'dashboard',
  'projectWorkspace',
  'qualityDashboard',
  'templates',
  'learning',
  'config'
];

export const state = {
  roles: [],
  users: [],
  clients: [],
  projects: [],
  members: [],
  workpapers: [],
  attachments: [],
  materials: [],
  tasks: [],
  runs: [],
  reviewFindings: [],
  templates: [],
  learningWeeks: [],
  learningDashboard: null,
  learningWeek: null,
  learningWeekCache: {},
  learningQuestionOpen: false,
  learningQuestionSearch: '',
  learningDifficultyFilter: '',
  learningChapterFilter: '',
  selectedLearningWeekId: null,
  selectedLearningQuestionId: null,
  overviewWorkpapers: [],
  autofillRuns: [],
  issueDashboard: null,
  activeSection: 'dashboard',
  activeProjectSubsection: 'projectWorkspace',
  activeBoardSubsection: 'issueDashboard',
  activeSystemSubsection: 'templates',
  ruleInspection: null,
  ruleVisualization: null,
  ruleCorrectionImports: [],
  autofillScopeConfig: null,
  selectedRuleInspectionId: null,
  clientIssuesByClient: {},
  workpaperTreeByProject: {},
  reviewStepsByWorkpaper: {},
  workpaperHeaderBatch: null,
  expandedWorkpaperTreeNodes: {},
  workpaperPreviews: {},
  me: null,
  selectedClientId: null,
  selectedClientIssueProjectId: null,
  selectedProjectId: null,
  selectedWorkpaperTreeNode: null,
  selectedWorkpaperId: null,
  editingProjectId: null,
  editingClientId: null,
  projectScopedLoading: false,
  moduleOrder: defaultModuleOrder.slice()
};

const tokenKey = 'audit_flow_token';

export function getToken() {
  return localStorage.getItem(tokenKey) || '';
}

export function setToken(token) {
  localStorage.setItem(tokenKey, token);
}

export function clearToken() {
  localStorage.removeItem(tokenKey);
}
