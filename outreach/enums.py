from enum import StrEnum


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    HOSPITAL_ADMIN = "hospital_admin"
    CAMPAIGN_MANAGER = "campaign_manager"
    CLINICAL_REVIEWER = "clinical_reviewer"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OutreachState(StrEnum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CALLING = "calling"
    CONNECTED = "connected"
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    VOICEMAIL = "voicemail"
    DROPPED = "dropped"
    RETRY_SCHEDULED = "retry_scheduled"
    CALLBACK_SCHEDULED = "callback_scheduled"
    ESCALATED = "escalated"
    MANUAL_FOLLOW_UP = "manual_follow_up"
    FAILED = "failed"


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    WAITING_FOR_INFORMATION = "waiting_for_information"
    RESOLVED = "resolved"
    CLOSED = "closed"
