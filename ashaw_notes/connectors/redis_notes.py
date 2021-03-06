#!/usr/bin/python3

""" Redis Note Connector module
"""
import re
import time
import redis
import ashaw_notes.utils.search
import ashaw_notes.utils.configuration


CONFIG_SECTION = 'redis_notes'
logger = ashaw_notes.utils.configuration.get_logger()


def is_enabled():
    """Checks if connector is enabled"""
    backends = ashaw_notes.utils.configuration.load_config().get('base_config', 'data_backends')
    return CONFIG_SECTION in backends


def save_note(timestamp, note):
    """Saves note to timestamp"""
    add_redis_note(timestamp, note)


def delete_note(timestamp):
    """Removes note at supplied timestamp"""
    delete_redis_note(timestamp)


def update_note(original_timestamp, new_timestamp, new_note):
    """Updates note at supplied timestamp"""
    delete_note(original_timestamp)
    save_note(new_timestamp, new_note)


def find_notes(search_terms):
    """Returns all notes corresponding to supplied search object"""
    request = ashaw_notes.utils.search.get_search_request(search_terms)
    return find_redis_notes(request)


def get_common_words():
    """Finds all common words in Redis"""
    redis_connection = get_redis_connection()
    words = redis_connection.keys(get_word_key("*"))
    return set([word[2:].decode('utf-8') for word in words])


# Module Specific Methods

__redis__ = None # reduces the number of simultaneous redis connections

def add_redis_note(timestamp, note):
    """Adds a note to redis"""
    redis_connection = get_redis_connection()
    tokens = get_note_tokens(timestamp, note)

    logger.debug("Adding %s tokens" % len(tokens))

    # Add search indices
    for token in tokens:
        redis_connection.sadd(token, timestamp)

    # Add notes
    logger.debug("Adding %s note" % timestamp)
    redis_connection.set(get_note_key(timestamp), note)


def delete_redis_note(timestamp):
    """Removes a note from redis"""
    redis_connection = get_redis_connection()

    if not redis_connection.exists(get_note_key(timestamp)):
        return

    line = redis_connection.get(get_note_key(timestamp)).decode('utf-8')
    tokens = get_note_tokens(timestamp, line)

    logger.debug("Deleting %s" % timestamp)
    logger.debug("Deleting %s tokens" % len(tokens))
    # Remove search indices
    for token in tokens:
        redis_connection.srem(token, timestamp)

    # Remove notes
    logger.debug("Deleting %s note" % timestamp)
    redis_connection.delete(get_note_key(timestamp))


def get_note_key(timestamp):
    """Generates redis keyname for timestamp"""
    return "note_%s" % timestamp


def get_word_key(word):
    """Generates redis keyname for word"""
    return "w_%s" % word.lower()


def get_note_tokens(timestamp, line):
    """Generates a list of tokens for a supplied note"""
    tokens = []
    parts = re.findall(r'(\w+)', line)
    for part in parts:
        token = get_word_key(part.lower())
        if token not in tokens:
            tokens.append(get_word_key(part.lower()))

    parts = re.findall(r'(#[A-z0-9-_]+)', line)
    for part in parts:
        token = get_word_key(part.lower())
        if token not in tokens:
            tokens.append(get_word_key(part.lower()))

    note_time = time.gmtime(timestamp)
    tokens.append("year_%s" % note_time.tm_year)
    tokens.append("month_%s" % note_time.tm_mon)
    tokens.append("day_%s" % note_time.tm_mday)
    tokens.append("hour_%s" % note_time.tm_hour)
    tokens.append("weekday_%s" % note_time.tm_wday)
    return tokens


def find_redis_notes(search_request):
    """Finds all notes related to the request"""
    redis_connection = get_redis_connection()
    timestamps = set([])

    if search_request.inclusion_terms:
        timestamps = redis_connection.sinter(
            [get_word_key(term)
             for term in search_request.inclusion_terms]
        )
        if search_request.exclusion_terms:
            timestamps = timestamps.difference(
                redis_connection.sunion(
                    [get_word_key(term)
                     for term in search_request.exclusion_terms]
                )
            )
    elif search_request.exclusion_terms:
        timestamps = set(
            [key[len(get_note_key('')):]
             for key in set(redis_connection.keys(get_note_key("*")))]
        )
        exclusion_timestamps = redis_connection.sunion(
            [get_word_key(term)
             for term in search_request.exclusion_terms]
        )

        timestamps = timestamps.difference(exclusion_timestamps)
    else:
        timestamps = [key[len(get_note_key('')):]
                      for key in set(redis_connection.keys(get_note_key("*")))]

    timestamps = [int(timestamp.decode('utf-8')) for timestamp in timestamps]
    timestamps.sort()

    if not timestamps:
        return [(None, None)]

    notes = redis_connection.mget([get_note_key(timestamp) for timestamp in timestamps])
    notes = [note.decode('utf-8') for note in notes]
    return list(zip(timestamps, notes))


def get_redis_connection():
    """Returns a common redis connection"""
    global __redis__

    config = ashaw_notes.utils.configuration.load_config()

    if not __redis__:
        __redis__ = redis.StrictRedis(
            host=config.get(CONFIG_SECTION, 'endpoint'),
            port=config.get(CONFIG_SECTION, 'port'),
            db=config.get(CONFIG_SECTION, 'db'),
            password=config.get(CONFIG_SECTION, 'password')
        )

    return __redis__
