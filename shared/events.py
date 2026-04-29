from enum import Enum

class StreamName(str, Enum):
    SCRAPE_RAW = "scrape.raw"
    ENTITY_UPDATED = "entity.updated"
    SCORE_COMPUTED = "score.computed"

class EntityType(str, Enum):
    PERSON = "person"
    STARTUP = "startup"

class ScrapeSource(str, Enum):
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    GITHUB = "github"
    CRUNCHBASE = "crunchbase"

class ScrapeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
