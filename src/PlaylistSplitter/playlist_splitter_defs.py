from enum import Enum

AUTHORIZATION_SCOPES = 'playlist-modify-private playlist-read-private playlist-modify-public'


class SplitTypes(Enum):
    ARTIST = 'artist'
    LABEL = 'label'
