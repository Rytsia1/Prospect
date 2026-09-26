"""Schema constraints against a real, migrated PostgreSQL. Runs when TEST_DATABASE_URL is set."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentType,
    PageExtractionStatus,
    ProcessingJob,
    User,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def session():
    url = Settings(database_url=TEST_DATABASE_URL).database_url
    with Session(create_engine(url)) as s:
        yield s
        s.rollback()


def make_document(session: Session, **overrides) -> Document:
    user = User(email=f"{uuid.uuid4()}@example.test")
    session.add(user)
    session.flush()
    doc = Document(
        user_id=user.id,
        filename="Annual_Report_2025.pdf",
        document_type=DocumentType.ANNUAL_REPORT,
        mime_type="application/pdf",
        storage_key=f"{user.id}/{uuid.uuid4()}.pdf",
        **overrides,
    )
    session.add(doc)
    session.flush()
    return doc


def page(doc: Document, number: int) -> DocumentPage:
    return DocumentPage(
        document_id=doc.id, page_number=number, extraction_status=PageExtractionStatus.SUCCESS
    )


def test_new_document_defaults_to_uploaded(session):
    assert make_document(session).status == DocumentStatus.UPLOADED


def test_page_numbers_unique_per_document(session):
    doc = make_document(session)
    session.add(page(doc, 87))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(page(doc, 87))
        session.flush()


def test_page_numbers_are_one_based(session):
    doc = make_document(session)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(page(doc, 0))
        session.flush()


def test_fiscal_year_is_range_checked(session):
    with pytest.raises(IntegrityError), session.begin_nested():
        make_document(session, fiscal_year=25)


def test_deleting_document_cascades(session):
    doc = make_document(session)
    session.add_all([page(doc, 1), ProcessingJob(document_id=doc.id)])
    session.flush()
    session.delete(doc)
    session.flush()
    session.expunge_all()
    for model in (DocumentPage, ProcessingJob):
        count = session.scalar(
            select(func.count()).select_from(model).where(model.document_id == doc.id)
        )
        assert count == 0
