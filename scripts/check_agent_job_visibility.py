# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright==1.58.0"]
# ///
"""Real-service Agent confirmation/list regression without model API calls.

All API requests go through the actual Next.js /api proxy. A succeeded task is
seeded only for a unique disposable account, and that account is removed finally.
"""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.environ.get("OFFERPILOT_TEST_BASE_URL", "http://localhost:3000")
BACKEND = Path(__file__).resolve().parents[1] / "backend"
ARTIFACTS = Path(tempfile.mkdtemp(prefix="offerpilot-agent-jobs-"))
RUN_ID = uuid4().hex
EMAIL = f"agent-live-{RUN_ID}@example.com"
COMPANY = f"真实链路验证公司{RUN_ID[:8]}"
TITLE = f"真实链路AI岗位{RUN_ID[:8]}"
USER_ID = None


def run_backend(code, scope):
    result = subprocess.run(
        [str(BACKEND / ".venv/bin/python"), "-c", code],
        input=json.dumps(scope),
        text=True,
        cwd=BACKEND,
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError("Scoped backend test setup/cleanup failed; no model call was made")
    return result.stdout.strip()


def seed_task(user_id):
    code = r'''
import json
import sys
from uuid import UUID
from sqlalchemy import select
from app.core.config import get_settings
from app.db import create_session_factory
from app.models import AgentRun, User, utc_now

scope = json.load(sys.stdin)
assert scope["email"].startswith("agent-live-") and scope["email"].endswith("@example.com")
owner_id = UUID(scope["user_id"])
engine, factory = create_session_factory(get_settings())
try:
    with factory() as session:
        user = session.scalar(select(User).where(User.id == owner_id, User.email == scope["email"]))
        assert user is not None, "Disposable account identity did not match"
        fields = {
            "company_name": {"value": scope["company"], "confidence": 0.99, "evidence": scope["company"]},
            "title": {"value": scope["title"], "confidence": 0.99, "evidence": scope["title"]},
            "city": {"value": "上海", "confidence": 0.95, "evidence": "工作地点上海"},
            "job_type": {"value": "校招", "confidence": 0.94, "evidence": "校招"},
            "batch": {"value": "2027 届秋招", "confidence": 0.95, "evidence": "2027 届秋招"},
            "deadline": {"value": scope["deadline"], "confidence": 0.98, "evidence": scope["deadline"]},
            "education_requirement": {"value": "本科及以上", "confidence": 0.94, "evidence": "本科及以上"},
            "required_skills": {"value": ["Python", "SQL"], "confidence": 0.94, "evidence": "Python 和 SQL"},
        }
        now = utc_now()
        run = AgentRun(
            user_id=user.id,
            task_type="job_extraction",
            status="succeeded",
            input_text=scope["source_text"],
            source_url=f"https://example.com/jobs/{scope['run_id']}",
            result={"fields": fields, "needs_review_fields": []},
            events=[{"id": 1, "event": "completed", "message": "真实服务测试任务已就绪。", "created_at": now.isoformat()}],
            model_name="synthetic-test-no-model-call",
            attempt_count=1,
            finished_at=now,
        )
        session.add(run)
        session.commit()
        print(json.dumps({"task_id": str(run.id)}))
finally:
    engine.dispose()
'''
    deadline = (date.today() + timedelta(days=60)).isoformat()
    source_text = (
        f"{COMPANY}招聘{TITLE}。工作地点上海，校招，批次 2027 届秋招。"
        f"截止日期 {deadline}，学历本科及以上，要求 Python 和 SQL。"
    )
    output = run_backend(code, {
        "email": EMAIL,
        "user_id": user_id,
        "company": COMPANY,
        "title": TITLE,
        "deadline": deadline,
        "source_text": source_text,
        "run_id": RUN_ID,
    })
    return json.loads(output)["task_id"], source_text


def cleanup():
    if USER_ID is None:
        return
    code = r'''
import json
import sys
from uuid import UUID
from sqlalchemy import delete, select
from app.core.config import get_settings
from app.db import create_session_factory
from app.models import (
    AgentRun, Application, ApplicationStatusEvent, CandidateProfile, Company,
    JobPosting, JobSourceEvidence, ResumeVersion, User,
)

scope = json.load(sys.stdin)
assert scope["email"].startswith("agent-live-") and scope["email"].endswith("@example.com")
owner_id = UUID(scope["user_id"])
engine, factory = create_session_factory(get_settings())
try:
    with factory() as session:
        user = session.scalar(select(User).where(User.email == scope["email"]))
        if user is not None:
            assert user.id == owner_id, "Disposable account identity did not match"
            for model in (
                JobSourceEvidence, AgentRun, ApplicationStatusEvent, Application,
                JobPosting, Company, CandidateProfile, ResumeVersion,
            ):
                session.execute(delete(model).where(model.user_id == owner_id))
            session.delete(user)
            session.commit()
        assert session.scalar(select(User.id).where(User.id == owner_id)) is None
    print("Disposable account and owned test records removed")
finally:
    engine.dispose()
'''
    print(run_backend(code, {"email": EMAIL, "user_id": USER_ID}), flush=True)


def matches_jobs_get(response):
    return response.request.method == "GET" and urlsplit(response.url).path == "/api/v1/jobs"


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(base_url=BASE_URL, viewport={"width": 1440, "height": 1000})
        context.set_default_timeout(15000)
        request = context.request
        registered = request.post(
            "/api/v1/auth/register",
            headers={"Origin": BASE_URL},
            data={"email": EMAIL, "password": secrets.token_urlsafe(24)},
        )
        assert registered.status == 201, f"Disposable registration returned HTTP {registered.status}"
        USER_ID = registered.json()["id"]

        for index in range(12):
            created = request.post(
                "/api/v1/jobs",
                headers={"Origin": BASE_URL},
                data={
                    "company_name": f"已有验证公司{RUN_ID[:8]}-{index + 1:02d}",
                    "title": f"已有验证岗位{index + 1:02d}",
                    "city": "上海",
                    "deadline": (date.today() + timedelta(days=index + 1)).isoformat(),
                    "description": "仅用于真实服务回归测试的合成岗位资料。",
                },
            )
            assert created.status == 201, f"Synthetic existing job returned HTTP {created.status}"
        task_id, source_text = seed_task(USER_ID)

        page = context.new_page()
        page_errors = []
        extraction_calls = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("request", lambda req: extraction_calls.append(req.url)
                if req.method == "POST" and urlsplit(req.url).path == "/api/v1/agent/job-extractions" else None)

        with page.expect_response(matches_jobs_get) as initial_response:
            page.goto("/jobs", wait_until="domcontentloaded")
        assert initial_response.value.status == 200
        expect(page.locator(".job-card")).to_have_count(12)
        page.get_by_role("button", name="AI 提取岗位", exact=True).click()
        expect(page.get_by_role("heading", name="提取完成，请核对", exact=True)).to_be_visible()
        expect(page.locator("label.agent-field").filter(has_text="职位").locator("input")).to_have_value(TITLE)

        with page.expect_response(
            lambda response: response.request.method == "POST"
            and urlsplit(response.url).path == f"/api/v1/agent/tasks/{task_id}/confirm"
        ) as confirmation_response:
            page.get_by_role("button", name="确认并保存岗位", exact=True).click()
        confirmed = confirmation_response.value
        assert confirmed.status == 201, f"Confirmation returned HTTP {confirmed.status}"
        saved_job = confirmed.json()
        job_id = saved_job["id"]

        listed = request.get("/api/v1/jobs")
        assert listed.status == 200
        jobs = listed.json()
        assert any(job["id"] == job_id for job in jobs), "Actual list API omitted confirmed job"
        api_position = next(index for index, job in enumerate(jobs) if job["id"] == job_id)
        print(f"Confirmed synthetic job exists in actual list API: position {api_position + 1}/{len(jobs)}", flush=True)

        expect(page.locator(".job-card")).to_have_count(13)
        expected_card_name = f"{COMPANY} {TITLE}"
        card = page.get_by_role("article", name=expected_card_name, exact=True)
        expect(card).to_have_count(1)
        box = card.bounding_box()
        print(f"Synthetic saved card before scrolling: {box}", flush=True)
        page.screenshot(path=str(ARTIFACTS / "agent-live-after-save.png"), full_page=False)
        expect(page.locator(".job-card").first).to_have_attribute("aria-label", expected_card_name)
        expect(card).to_be_in_viewport()

        evidence = request.get(f"/api/v1/agent/jobs/{job_id}/evidence")
        assert evidence.status == 200
        assert evidence.json()["source_text"] == source_text

        # Delay a real, empty filtered response until after opening the saved job.
        # Without request ordering protection it overwrites the refreshed list.
        empty_search = f"visibility-missing-{RUN_ID}"
        held_responses = []

        def hold_filtered_response(route):
            held_responses.append((route, route.fetch()))

        page.route(re.compile(r".*/api/v1/jobs\?search=visibility-missing-.*"), hold_filtered_response)
        page.get_by_label("公司 / 职位 / 行业").fill(empty_search)
        with page.expect_request(
            lambda req: urlsplit(req.url).path == "/api/v1/jobs"
            and parse_qs(urlsplit(req.url).query).get("search") == [empty_search]
        ):
            page.get_by_role("button", name="筛选", exact=True).click()
        for _ in range(30):
            if held_responses:
                break
            page.wait_for_timeout(50)
        assert held_responses, "Could not capture the real filtered response"
        assert held_responses[0][1].json() == []

        page.get_by_role("button", name="AI 提取岗位", exact=True).click()
        page.get_by_role("button", name="查看已保存岗位", exact=True).click()
        expect(page.locator(".job-card")).to_have_count(13)
        expect(page.get_by_role("article", name=expected_card_name, exact=True)).to_be_in_viewport()
        expect(page.get_by_label("公司 / 职位 / 行业")).to_have_value("")
        with page.expect_response(
            lambda response: parse_qs(urlsplit(response.url).query).get("search") == [empty_search]
        ):
            held_responses[0][0].fulfill(response=held_responses[0][1])
        page.wait_for_timeout(300)
        expect(page.locator(".job-card")).to_have_count(13)
        expect(page.locator(".job-card").first).to_have_attribute("aria-label", expected_card_name)
        print("PASS: restored saved-job navigation and delayed old response cannot erase the saved card", flush=True)

        with page.expect_response(matches_jobs_get) as reload_response:
            page.reload(wait_until="domcontentloaded")
        assert reload_response.value.status == 200
        expect(page.locator(".job-card")).to_have_count(13)
        expect(page.locator(".job-card").first).to_have_attribute("aria-label", expected_card_name)
        expect(page.get_by_role("article", name=expected_card_name, exact=True)).to_be_in_viewport()

        # Viewing an older saved task must stay visible after the list refresh
        # even when more recently created jobs normally sort ahead of it.
        for index in range(3):
            newer = request.post(
                "/api/v1/jobs",
                headers={"Origin": BASE_URL},
                data={
                    "company_name": f"稍后验证公司{RUN_ID[:8]}-{index}",
                    "title": f"稍后验证岗位{index}",
                    "description": "仅用于较早已保存任务定位回归。",
                },
            )
            assert newer.status == 201
        with page.expect_response(matches_jobs_get):
            page.reload(wait_until="domcontentloaded")
        expect(page.locator(".job-card")).to_have_count(16)
        expect(page.locator(".job-card").first).not_to_have_attribute("aria-label", expected_card_name)
        page.get_by_role("button", name="AI 提取岗位", exact=True).click()
        with page.expect_response(matches_jobs_get):
            page.get_by_role("button", name="查看已保存岗位", exact=True).click()
        expect(page.locator(".job-card").first).to_have_attribute("aria-label", expected_card_name)
        expect(page.get_by_role("article", name=expected_card_name, exact=True)).to_be_in_viewport()
        print("PASS: older saved task remains visible after newer jobs and authoritative list refresh", flush=True)
        assert not page_errors, f"Synthetic test page errors: {page_errors}"
        assert not extraction_calls, "Unexpected model-extraction API request"
        print("PASS: real confirmation, list API, first visible saved card, evidence and reload persistence", flush=True)
        browser.close()
finally:
    cleanup()
