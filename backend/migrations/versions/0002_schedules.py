"""One-time schedules and a persistent execution ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("schedules", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel_id", sa.String(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False), sa.Column("timezone", sa.String(), nullable=False))
    op.create_table("scheduled_events", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("schedule_id", sa.String(), sa.ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_id", sa.String(), sa.ForeignKey("media_assets.id"), nullable=False),
        sa.Column("label", sa.String(), nullable=False), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("preferred_start", sa.String(), nullable=False), sa.Column("max_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("user_fields", sa.JSON(), nullable=False))
    op.create_table("schedule_executions", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey("scheduled_events.id"), unique=True, nullable=False),
        sa.Column("planned_start", sa.String(), nullable=False), sa.Column("planned_end", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("command_at", sa.String()),
        sa.Column("observed_at", sa.String()), sa.Column("ended_at", sa.String()), sa.Column("error", sa.String()),
        sa.Column("snapshot", sa.JSON(), nullable=False))


def downgrade():
    for table in ("schedule_executions", "scheduled_events", "schedules"):
        op.drop_table(table)
