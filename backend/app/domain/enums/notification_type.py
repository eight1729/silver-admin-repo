"""Notification types introduced for the local-demo application flow."""

from enum import Enum


class NotificationType(str, Enum):
    NEW_JOB_MATCH = "new_job_match"
    EXISTING_JOB_MATCH = "existing_job_match"
    CUSTOM_JOB = "custom_job"