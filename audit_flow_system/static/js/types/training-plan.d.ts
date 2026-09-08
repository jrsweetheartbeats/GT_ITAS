export type TrainingPlanSchemaVersion = "1.0";

export type TrainingTaskType =
  | "learning"
  | "quiz"
  | "practice"
  | "project"
  | "assignment"
  | "self_check"
  | "review";

export type LearningMaterialType =
  | "itas_page"
  | "external_link"
  | "document"
  | "video"
  | "case"
  | "reference";

export type LearningMaterialScope = "common" | "personal";

export interface TrainingPlanEmployee {
  code: string;
  name: string;
}

export interface TrainingPlanInfo {
  title: string;
  type: string;
  period: string;
  startDate: string;
  endDate: string;
  overallGoal: string;
  mentorCode: string;
}

export interface LearningMaterial {
  title: string;
  type: LearningMaterialType;
  /** Defaults to personal for backward-compatible plan imports. */
  courseScope?: LearningMaterialScope;
  url: string;
  description: string;
}

export interface TaskSubmissionSpec {
  required: boolean;
  submissionType: string;
  title: string;
  requirements: string;
}

export interface TrainingQuizQuestion {
  type: "choice" | "fill_blank";
  prompt: string;
  options?: string[];
  answer: string | string[];
}

export interface TrainingTask {
  taskCode: string;
  title: string;
  taskType: TrainingTaskType;
  description: string;
  purpose?: string;
  startDate: string;
  dueDate: string;
  estimatedHours: number;
  prerequisiteTaskCodes: string[];
  learningMaterials: LearningMaterial[];
  instructions: string;
  submission: TaskSubmissionSpec;
  completionCriteria: string;
  selfCheckQuestions?: Array<string | TrainingQuizQuestion>;
  mentorReviewRequired: boolean;
}

export interface TrainingWeek {
  weekNo: number;
  title: string;
  objective: string;
  startDate: string;
  endDate: string;
  expectedDeliverable: string;
  tasks: TrainingTask[];
}

export interface AssessmentDimension {
  code: string;
  name: string;
  weight: number;
  description: string;
}

export interface AssessmentThreshold {
  min: number;
  max: number;
  nextAction: string;
}

export interface TrainingPlanAssessment {
  dimensions: AssessmentDimension[];
  totalScore: 100;
  thresholds: AssessmentThreshold[];
}

export interface TrainingPlanDocument {
  schemaVersion: TrainingPlanSchemaVersion;
  employee: TrainingPlanEmployee;
  plan: TrainingPlanInfo;
  weeks: TrainingWeek[];
  assessment: TrainingPlanAssessment;
}
