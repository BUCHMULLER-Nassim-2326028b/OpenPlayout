"""Initial persistent media, channel, rundown and as-run schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("channels", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False), sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("fps_num", sa.Integer(), nullable=False), sa.Column("fps_den", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False), sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False))
    op.create_table("media_assets", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False), sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False))
    op.create_table("media_locations", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("media_id", sa.String(), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("path", sa.String(), unique=True, nullable=False), sa.Column("root", sa.String(), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False), sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime_ns", sa.Integer(), nullable=False), sa.Column("missing", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String()))
    op.create_table("playlists", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel_id", sa.String(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False), sa.Column("cursor_id", sa.String()))
    op.create_table("playlist_items", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("playlist_id", sa.String(), sa.ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_id", sa.String(), sa.ForeignKey("media_assets.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False), sa.UniqueConstraint("playlist_id", "position"))
    op.create_table("playback_history", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel_id", sa.String(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("item_id", sa.String()), sa.Column("media_id", sa.String(), sa.ForeignKey("media_assets.id"), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False), sa.Column("ended_at", sa.String()),
        sa.Column("outcome", sa.String(), nullable=False))
    op.create_table("application_settings", sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False))


def downgrade():
    for table in ["application_settings", "playback_history", "playlist_items", "playlists", "media_locations", "media_assets", "channels"]:
        op.drop_table(table)
