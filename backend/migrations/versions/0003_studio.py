"""Chapters, virtual segments, collections, versioned templates and runtime audit."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for name, nullable in (("chapters", True), ("segments", False)):
        columns = [sa.Column("id", sa.String(), primary_key=True), sa.Column("media_id", sa.String(), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("label", sa.String(), nullable=False), sa.Column("in_frame", sa.Integer(), nullable=False), sa.Column("out_frame", sa.Integer(), nullable=nullable),
            sa.Column("fps_num", sa.Integer(), nullable=False), sa.Column("fps_den", sa.Integer(), nullable=False)]
        if name == "chapters":
            columns += [sa.Column("kind", sa.String(), nullable=False), sa.Column("notes", sa.String(), nullable=False), sa.Column("triggers", sa.JSON(), nullable=False)]
        op.create_table(name, *columns)
    with op.batch_alter_table("playlist_items") as batch:
        batch.add_column(sa.Column("segment_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_playlist_segment", "segments", ["segment_id"], ["id"])
        batch.add_column(sa.Column("transition", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("scheduled_events") as batch:
        batch.add_column(sa.Column("segment_id", sa.String()))
        batch.create_foreign_key("fk_schedule_segment", "segments", ["segment_id"], ["id"])
    op.create_table("collections", sa.Column("id", sa.String(), primary_key=True), sa.Column("name", sa.String(), nullable=False), sa.Column("query", sa.JSON(), nullable=False))
    op.create_table("collection_items", sa.Column("id", sa.String(), primary_key=True), sa.Column("collection_id", sa.String(), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_id", sa.String(), sa.ForeignKey("media_assets.id"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("weight", sa.Integer(), nullable=False), sa.UniqueConstraint("collection_id", "media_id"))
    op.create_table("resources", sa.Column("id", sa.String(), primary_key=True), sa.Column("kind", sa.String(), nullable=False), sa.Column("name", sa.String(), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False))
    op.create_table("graphics_instances", sa.Column("id", sa.String(), primary_key=True), sa.Column("template_id", sa.String(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("channel_id", sa.String(), sa.ForeignKey("channels.id"), nullable=False), sa.Column("layer", sa.Integer(), nullable=False), sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("access_key", sa.String(), nullable=False), sa.Column("state", sa.String(), nullable=False), sa.Column("error", sa.String()))
    op.create_table("automation_events", sa.Column("id", sa.String(), primary_key=True), sa.Column("hook", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("outcome", sa.String(), nullable=False))
    op.create_table("playout_sessions", sa.Column("id", sa.String(), primary_key=True), sa.Column("channel_id", sa.String(), sa.ForeignKey("channels.id"), nullable=False), sa.Column("updated_at", sa.String(), nullable=False), sa.Column("state", sa.String(), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False))


def downgrade():
    for name in ("playout_sessions", "automation_events", "graphics_instances", "resources", "collection_items", "collections"):
        op.drop_table(name)
    with op.batch_alter_table("playlist_items") as batch:
        batch.drop_constraint("fk_playlist_segment", type_="foreignkey")
        batch.drop_column("segment_id")
        batch.drop_column("transition")
    with op.batch_alter_table("scheduled_events") as batch:
        batch.drop_constraint("fk_schedule_segment", type_="foreignkey")
        batch.drop_column("segment_id")
    op.drop_table("segments")
    op.drop_table("chapters")
