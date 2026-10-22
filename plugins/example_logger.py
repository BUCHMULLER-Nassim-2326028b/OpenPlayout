"""Trusted opt-in plugin. Enable with OPENPLAYOUT_TRUSTED_PLUGINS=[\"example_logger.py\"]."""
import logging

log = logging.getLogger('app.plugin.example')


def register(events):
    def on_event(hook, payload):
        item = payload.get('item') or {}
        log.info('Plugin received %s for item %s', hook, item.get('id'))
    events.subscribe('program.changed', on_event)
    events.subscribe('playback.error', on_event)
