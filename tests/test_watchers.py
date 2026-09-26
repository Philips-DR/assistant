"""Tests for job notifications. The decisions are pure functions, so no server is needed."""

from assistant.watchers import login_notice, recording_notice, transcription_notice


def job(state, **extra):
    return {"id": "j1", "audio": "/x/meeting.m4a", "state": state, **extra}


def test_a_finished_transcription_is_announced():
    notice = transcription_notice("running", job("done"))
    assert notice["title"] == "Transcript ready"
    assert "meeting.m4a" in notice["body"]


def test_a_failure_says_why():
    notice = transcription_notice("running", job("failed", detail="ffmpeg could not decode"))
    assert notice["level"] == "error"
    assert "could not decode" in notice["body"]


def test_an_interruption_is_not_called_a_failure():
    """Killed or slept is not an error, and restarting resumes -- so it must not read as one."""
    notice = transcription_notice("running", job("interrupted"))
    assert notice["level"] == "warning"
    assert "resumes" in notice["body"]


def test_nothing_is_announced_on_the_first_sighting_of_a_finished_job():
    """A job that was already done when the server started is old news. Announcing it on every
    restart would teach people to ignore the notifications."""
    assert transcription_notice(None, job("done")) is None


def test_nothing_is_announced_while_a_job_is_still_running():
    assert transcription_notice("running", job("running")) is None


def test_a_recording_that_dies_mid_meeting_is_announced():
    notice = recording_notice("recording", {"id": "r1", "state": "orphaned"})
    assert notice["title"] == "Recording interrupted"


def test_a_recording_stopped_normally_is_not_an_alarm():
    assert recording_notice("recording", None) is None


def test_a_failing_login_is_announced_once_with_the_fix():
    status = {"level": "error", "hint": "Run `aws sso login --profile ayadata-bedrock` in a terminal."}
    notice = login_notice("ok", status)
    assert notice["title"] == "AWS login needs renewing"
    assert "aws sso login" in notice["body"]
    assert login_notice("error", status) is None  # not again on every poll


def test_a_login_that_recovers_says_so():
    assert login_notice("error", {"level": "ok"})["title"] == "AWS login working again"
    assert login_notice(None, {"level": "ok"}) is None
