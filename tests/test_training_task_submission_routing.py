from types import SimpleNamespace

from audit_flow_system.routers.development_import import _related_submission_task, _validate_task_questions


def _task(task_id, *, required, title, questions, sort_order):
    return SimpleNamespace(
        id=task_id,
        submission_required=required,
        submission_title=title,
        title=title,
        self_check_questions=questions,
        sort_order=sort_order,
        training_week=None,
    )


def test_learning_task_points_to_its_weekly_submission_with_question_count():
    learning_task = _task(10, required=False, title="学习与训练", questions="[]", sort_order=10)
    assignment = _task(
        11,
        required=True,
        title="当周正式作业",
        questions='[{"type":"choice","prompt":"题目","options":["A","B"],"answer":"A"}]',
        sort_order=20,
    )
    week = SimpleNamespace(tasks=[learning_task, assignment])
    learning_task.training_week = week
    assignment.training_week = week

    assert _related_submission_task(learning_task) == {
        "id": 11,
        "title": "当周正式作业",
        "questionCount": 1,
        "submissionRequired": True,
    }
    assert _related_submission_task(assignment) is None


def test_choice_answers_remain_required_before_submission():
    questions = [{"type": "choice", "prompt": "题目", "options": ["A", "B"], "answer": "A"}]
    assert _validate_task_questions(questions, {}) == (["题目"], [])
    assert _validate_task_questions(questions, {"0": "B"}) == ([], ["题目"])
    assert _validate_task_questions(questions, {"0": "A"}) == ([], [])
