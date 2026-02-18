from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from use_cases.actions import UseCaseValidationError
from use_cases.archive import NotFoundError
from use_cases.decision_records import UseCaseIntegrityError as DecisionIntegrityError
from use_cases.hypotheses import UseCaseIntegrityError as HypothesisIntegrityError
from use_cases.transitions import ForbiddenTransitionError


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain/use-case exception -> HTTP mappings."""

    @app.exception_handler(NotFoundError)
    def _not_found(_req: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DecisionIntegrityError)
    def _decision_integrity(_req: Request, exc: DecisionIntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(HypothesisIntegrityError)
    def _hypothesis_integrity(_req: Request, exc: HypothesisIntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(UseCaseValidationError)
    def _use_case_validation(_req: Request, exc: UseCaseValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ForbiddenTransitionError)
    def _forbidden_transition(_req: Request, exc: ForbiddenTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
