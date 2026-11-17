from signal_loop_agents.inbox import parse_event_from_linear


def test_issue_event_is_keyed_by_identifier():
    payload = {"action": "update", "data": {"id": "uuid-1", "identifier": "SIG-7"}}
    event = parse_event_from_linear("d-1", "Issue", payload)
    assert (event.action, event.issue_id) == ("update", "SIG-7")
    assert event.payload is payload


def test_issue_event_without_identifier_falls_back_to_uuid():
    event = parse_event_from_linear("d-1", "Issue", {"data": {"id": "uuid-1"}})
    assert event.issue_id == "uuid-1"


def test_comment_event_is_keyed_by_its_issue_identifier():
    payload = {
        "action": "create",
        "data": {"id": "c-1", "issueId": "uuid-1", "issue": {"id": "uuid-1", "identifier": "SIG-7"}},
    }
    assert parse_event_from_linear("d-2", "Comment", payload).issue_id == "SIG-7"


def test_comment_without_issue_object_falls_back_to_uuid():
    event = parse_event_from_linear("d-3", "Comment", {"data": {"id": "c-1", "issueId": "uuid-1"}})
    assert event.issue_id == "uuid-1"


def test_other_events_have_no_issue():
    event = parse_event_from_linear("d-4", "Project", {"action": "update", "data": {"id": "p-1"}})
    assert event.issue_id is None
