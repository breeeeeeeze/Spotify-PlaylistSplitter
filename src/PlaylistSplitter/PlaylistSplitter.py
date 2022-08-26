import os
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Optional, Generator, Callable

import spotipy
from spotipy import SpotifyOAuth
from tqdm import tqdm

from PlaylistSplitter.playlist_splitter_defs import AUTHORIZATION_SCOPES, SplitTypes


@dataclass
class SpotifyCredentials:
    client_id: str
    client_secret: str
    redirect_uri: str

class PlaylistSplitter:
    """
    # PlaylistSplitter

    Splits playlists up by custom parameters, such as by artists or labels
    """

    def __init__(self, login: Optional[spotipy.Spotify | dict[str, Any]] = None):
        """

        :param login: spotify client or dict with spotify credentials
        """
        self.client: Optional[spotipy.Spotify] = None
        self.credentials: Optional[SpotifyCredentials] = None
        if isinstance(login, spotipy.Spotify):
            self.client = login
        if isinstance(login, dict):
            self.credentials = SpotifyCredentials(**login)
        self.__origin_playlist: Optional[str] = None
        self.__target_playlists: Optional[list[str]] = None
        self.__split_type: Optional[str] = None
        self.__split_pools: Optional[list[set[str]]] = None

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        ...

    def __get_credentials_from_env(self):
        client_id = os.getenv('SPOTIFY_CLIENT_ID')
        client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')
        self.credentials = SpotifyCredentials(client_id=client_id, client_secret=client_secret,
                                              redirect_uri=redirect_uri)

    def __spotify_login(self):
        if any(x is None for x in asdict(self.credentials).values()):
            raise ValueError(
                'Credentials not found, '
                'make sure to pass them on instantiation or provide them in environment variables')
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=self.credentials.client_id,
                client_secret=self.credentials.client_secret,
                redirect_uri=self.credentials.redirect_uri,
                scope=AUTHORIZATION_SCOPES
            )
        )

    def login(self, credentials: Optional[dict[str, str]] = None):
        if credentials:
            self.credentials = SpotifyCredentials(**credentials)
        if not self.credentials:
            self.__get_credentials_from_env()
        self.__spotify_login()

    def by(self, split_by: SplitTypes, split_lists: list[list[str]]):
        print(f'Split by {split_by}')
        self.__split_type = split_by
        self.__split_pools = split_lists
        return self

    def split_by(self, *args, **kwargs):
        return self.by(*args, **kwargs)

    def playlist(self, playlist_id: str):
        self.__origin_playlist = playlist_id
        return self

    def into(self, playlist_ids: list[str]):
        self.__target_playlists = playlist_ids
        return self

    def split(self, /, *, by: Optional[tuple[str, list[str]]] = None, playlist: Optional[str] = None,
              into: Optional[list[str]] = None):
        """
        Split the playlist. Parameters can be passed here as keyword arguments if not set previously

        :param by: Tuple of what to split by (artist or label) and a list of groups.
                    Groups must contain ID, URI or URL (artist) or name (label).
        :param playlist: What playlist to split. Must be an ID, URI or URL
        :param into: Target playlists to split into (must be same number as split pools).
                      Must be list of IDs, URIs or URLs
        """
        if by is not None:
            self.by(*by)
        if playlist is not None:
            self.playlist(playlist)
        if into is not None:
            self.into(into)
        if any(x is None for x in (self.__origin_playlist, self.__split_type, self.__split_pools)):
            raise ValueError('Playlist and split settings must be set to perform split')
        if self.__target_playlists is not None and (
                len(self.__split_pools) != len(self.__target_playlists)
                and len(self.__split_pools) + 1 != len(self.__target_playlists)):
            raise ValueError('List of target playlists must be same length as split pools (or unset)')
        if not self.__target_playlists:
            self.__target_playlists = (self.__make_target_playlist() for _ in range(len(self.__split_pools)))
        self.__do_split()
        print('Split done!')

    def __do_split(self):
        """
        Internal method to do the actual splitting process
        :return:
        """
        origin_tracks = [result['track'] for result in self.__get_all_playlist_items(self.__origin_playlist)]

        # track_pools = self.__split_by_artist(origin_tracks)
        # Split depending on split type
        track_pools = getattr(self, '_PlaylistSplitter__split_by_' + self.__split_type)(origin_tracks)
        for tracks, playlist in zip(track_pools, self.__target_playlists, strict=True):
            self.reset_playlist(playlist)
            self.write_playlist(playlist, tracks)

    def __split_by_artist(self, tracks: list[dict[str, Any]]) -> list[list[str]]:
        """
        Split tracks by artists
        :param tracks:
        :return:
        """
        slimmed_tracks = [{'id': track['id'], 'artists': {artist['id'] for artist in track['artists']}} for track in
                          tracks]
        track_pools = [list() for _ in range(len(self.__split_pools) + 1)]
        for track in tqdm(slimmed_tracks, desc='Splitting tracks'):
            for idx, pool in enumerate(self.__split_pools):
                if track['artists'].intersection(set(pool)):
                    track_pools[idx].append(track['id'])
                    break
            else:
                track_pools[-1].append(track['id'])
        return track_pools

    def __split_by_label(self, tracks: list[dict[str, Any]]) -> list[list[str]]:
        """
        Split tracks by labels.
        :param tracks:
        :return:
        """
        # Get details of each track from spotify API to extract the label
 #       slimmed_tracks = [{'id': track['id'], 'label': self.client.album(track['album']['id'])['label']} for track in tracks]
        track_pools = [list() for _ in range(len(self.__split_pools) + 1)]
        for track in tqdm(self.__label_track_slimmer(tracks), desc='Splitting tracks', total=len(tracks)):
            for idx, pool in enumerate(self.__split_pools):
                if track['label'] in pool:
                    track_pools[idx].append(track['id'])
                    break
            else:
                track_pools[-1].append(track['id'])
        return track_pools

    def __label_track_slimmer(self, tracks: list[dict[str, Any]]):
        """
        Yield details from each track from spotify API to extract the label
        :param tracks:
        :return:
        """
        for track in tracks:
            yield {'id': track['id'], 'label': self.client.album(track['album']['id'])['label']}

    def __make_target_playlist(self) -> str:
        """
        Internal method to automatically create target playlists and return their IDs

        :return: List of playlist IDs
        """
        return self.client.user_playlist_create(self.client.current_user()['id'], 'test1')

    def __get_all_playlist_items(self, playlist_id):
        playlist_tracks = []
        results = self.client.playlist(playlist_id)
        playlist_tracks.extend(results['tracks']['items'])
        while results['tracks']['next']:
            results['tracks'] = self.client.next(results['tracks'])
            playlist_tracks.extend(results['tracks']['items'])
        return playlist_tracks

    @staticmethod
    def chunk_track_list(tracks: list[str]) -> Generator[list[dict[str, Any]], None, None]:
        """
        Split the playlist into chunks to avoid the Spotify API limit
        """
        for i in range(0, len(tracks), 50):
            yield tracks[i: i + 50]

    def write_playlist(self, playlist: str, track_list: list[str]) -> None:
        """
        Write the playlist to the Spotify API
        """
        self.reset_playlist(playlist)
        chunked_list = list(self.chunk_track_list(track_list))
        for chunk in tqdm(chunked_list, desc='Writing playlist'):
            self.client.playlist_add_items(playlist, chunk)

    def reset_playlist(self, playlist_id: str) -> None:
        """
        Remove all elements in the playlist
        """
        self.client.playlist_replace_items(playlist_id, ['spotify:track:4RWkW7tGWseUu1T9LzpEBP'])
        self.client.playlist_remove_all_occurrences_of_items(
            playlist_id, ['spotify:track:4RWkW7tGWseUu1T9LzpEBP']
        )
