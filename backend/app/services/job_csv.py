"""Parse and validate job CSV files without persisting or trusting row data."""

import csv
from dataclasses import dataclass
from io import StringIO
import re
from typing import Any

from pydantic import ValidationError

from app.schemas import JobPostingWrite

MAX_JOB_CSV_BYTES = 5 * 1024 * 1024
MAX_JOB_CSV_ROWS = 500

CSV_HEADERS = (
    "公司名称",
    "公司官网",
    "招聘主页",
    "行业",
    "公司备注",
    "职位名称",
    "城市",
    "岗位类型",
    "招聘批次",
    "截止日期",
    "学历要求",
    "技能要求",
    "岗位描述",
    "岗位来源",
    "来源类型",
    "标签",
)

_HEADER_ALIASES = {
    "company_name": "company_name",
    "公司名称": "company_name",
    "company_website_url": "company_website_url",
    "公司官网": "company_website_url",
    "recruitment_url": "recruitment_url",
    "招聘主页": "recruitment_url",
    "industry": "industry",
    "行业": "industry",
    "company_notes": "company_notes",
    "公司备注": "company_notes",
    "title": "title",
    "职位名称": "title",
    "city": "city",
    "城市": "city",
    "job_type": "job_type",
    "岗位类型": "job_type",
    "batch": "batch",
    "招聘批次": "batch",
    "deadline": "deadline",
    "截止日期": "deadline",
    "education_requirement": "education_requirement",
    "学历要求": "education_requirement",
    "required_skills": "required_skills",
    "技能要求": "required_skills",
    "description": "description",
    "岗位描述": "description",
    "source_url": "source_url",
    "岗位来源": "source_url",
    "source_type": "source_type",
    "来源类型": "source_type",
    "tags": "tags",
    "标签": "tags",
}

_FIELD_LABELS = {
    "company_name": "公司名称",
    "company_website_url": "公司官网",
    "recruitment_url": "招聘主页",
    "industry": "行业",
    "company_notes": "公司备注",
    "title": "职位名称",
    "city": "城市",
    "job_type": "岗位类型",
    "batch": "招聘批次",
    "deadline": "截止日期",
    "education_requirement": "学历要求",
    "required_skills": "技能要求",
    "description": "岗位描述",
    "source_url": "岗位来源",
    "source_type": "来源类型",
    "tags": "标签",
}


class JobCsvImportError(ValueError):
    """Raised when a CSV file cannot be interpreted as job records."""


@dataclass(frozen=True)
class ParsedJobCsvRow:
    """One row with a validated payload or row-level errors."""

    row_number: int
    data: JobPostingWrite | None
    fields: dict[str, str]
    errors: list[str]


def build_job_csv_template() -> str:
    """Return a blank CSV template with Chinese headers and UTF-8 BOM."""

    buffer = StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerow(CSV_HEADERS)
    return "\ufeff" + buffer.getvalue()


def parse_job_csv(data: bytes) -> list[ParsedJobCsvRow]:
    """Decode, map headers, and validate up to 500 rows without saving them."""

    if not data:
        raise JobCsvImportError("CSV 文件不能为空")
    if len(data) > MAX_JOB_CSV_BYTES:
        raise JobCsvImportError("CSV 文件不能超过 5 MB")
    try:
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = data.decode("gb18030")
        reader = csv.DictReader(StringIO(decoded, newline=""), strict=True)
        if not reader.fieldnames:
            raise JobCsvImportError("CSV 文件缺少表头")

        mapped_headers: list[tuple[str, str]] = []
        seen_fields: set[str] = set()
        for header in reader.fieldnames:
            normalized = (header or "").strip().casefold()
            field = _HEADER_ALIASES.get(normalized)
            if field is None:
                continue
            if field in seen_fields:
                raise JobCsvImportError(f"CSV 中重复出现“{_FIELD_LABELS[field]}”列")
            seen_fields.add(field)
            mapped_headers.append((header, field))
        if not seen_fields.intersection({"company_name", "title", "source_url", "description"}):
            raise JobCsvImportError("CSV 表头无法识别，请下载并使用岗位导入模板")

        parsed_rows: list[ParsedJobCsvRow] = []
        for row_number, raw_row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in raw_row.values()):
                continue
            if len(parsed_rows) >= MAX_JOB_CSV_ROWS:
                raise JobCsvImportError(f"CSV 最多支持 {MAX_JOB_CSV_ROWS} 条岗位")

            raw_fields = {
                field: str(raw_row.get(header) or "").strip()
                for header, field in mapped_headers
            }
            row_has_extra_cells = None in raw_row and bool(raw_row[None])
            payload_values: dict[str, Any] = dict(raw_fields)
            payload_values["deadline"] = raw_fields.get("deadline") or None
            for field in ("required_skills", "tags"):
                payload_values[field] = [
                    item.strip()
                    for item in re.split(r"[,，;；|]", raw_fields.get(field, ""))
                    if item.strip()
                ]
            if not payload_values.get("source_type"):
                payload_values["source_type"] = "manual"

            try:
                payload = JobPostingWrite.model_validate(payload_values)
                errors = ["该行列数多于表头，请检查 CSV 的逗号和引号"] if row_has_extra_cells else []
                if errors:
                    payload = None
            except ValidationError as exc:
                payload = None
                errors = _format_validation_errors(exc)
                if row_has_extra_cells:
                    errors.append("该行列数多于表头，请检查 CSV 的逗号和引号")
            parsed_rows.append(
                ParsedJobCsvRow(
                    row_number=row_number,
                    data=payload,
                    fields=raw_fields,
                    errors=errors,
                )
            )
        if not parsed_rows:
            raise JobCsvImportError("CSV 中没有可导入的岗位行")
        return parsed_rows
    except UnicodeDecodeError as exc:
        raise JobCsvImportError("文件编码无法识别，请保存为 UTF-8 或 GB18030 CSV") from exc
    except csv.Error as exc:
        raise JobCsvImportError("CSV 格式无法解析，请检查引号或分隔符") from exc


def _format_validation_errors(error: ValidationError) -> list[str]:
    """Convert Pydantic row errors into concise Chinese import feedback."""

    messages: list[str] = []
    for item in error.errors():
        location = item.get("loc", ())
        field = str(location[0]) if location else ""
        label = _FIELD_LABELS.get(field)
        if not field:
            message = str(item["msg"]).removeprefix("Value error, ")
        elif item.get("type") == "string_too_long":
            message = f"{label or field}内容过长"
        elif field in {"source_url", "company_website_url", "recruitment_url"}:
            message = f"{label}必须是以 http:// 或 https:// 开头的链接"
        elif field == "deadline":
            message = "截止日期格式应为 YYYY-MM-DD"
        elif field == "source_type":
            message = "来源类型只支持 manual、paste 或 link"
        else:
            message = str(item["msg"]).removeprefix("Value error, ")
            if label:
                message = f"{label}：{message}"
        if message not in messages:
            messages.append(message)
    return messages
