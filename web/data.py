import hashlib
import io
from urllib.parse import urljoin
from typing import Any, Dict, Generator, Tuple

from google.cloud import firestore, storage
from google.cloud.storage import Blob

from PIL import Image
from wordcloud import WordCloud

from .models import Publication, WordCount


def get_client(_type='db'):
    '''get_client returns a client used for accessessing data or blob storage. 
    '''
    if _type == 'db':
        return firestore.Client()
    elif _type == 'blob':
        return storage.Client()
    else:
        raise ValueError('unknown client type')


def image_to_byte_array(image: Image.Image, fmt: str = 'png'):
    '''Converts a PIL.Image.Image to a byte array, encoded as a PNG'''
    ioba = io.BytesIO()
    image.save(ioba, format=fmt)
    return ioba.getvalue()


def generate_word_cloud(freqs, fmt: str = 'bytes', height: int = 500, width: int = 500) -> Any:
    '''Generates a word cloud PIL.Image.Image of 500px X 500px
    Uses fmt to determine how to return the word cloud.
        Options: raw, image, bytes
    '''
    wc = WordCloud(height=height, width=width)
    wc.fit_words(freqs)
    fmt = fmt.lower()

    if fmt == 'raw':
        return wc
    elif fmt == 'image':
        return wc.to_image()
    elif fmt == 'bytes':
        return image_to_byte_array(wc.to_image())
    else:
        raise ValueError('unsupported fmt value.')


def image_url_path(pub_id: str, path: str = '/') -> str:
    '''create a URL path based on the provided publication id, and base path'''
    # If None or empty set to the default of forward slash
    path = path or '/'

    if path != '/':
        # Ensure that the path starts and ends with a forward slash
        # Break the path apart to remove all the forward slashes
        path = path.split('/')
        # Reassemble ensuring to remove multiple slashes. for example: /path// becomes /path/
        path = '/{}/'.format('/'.join([p for p in path if p]))

    return urljoin(path, f'{hashlib.md5(pub_id.encode()).hexdigest()}.png')


class DataStorage():

    def __init__(self, client: firestore.Client = None):
        self.db = client

    def publications(self, bucket_name: str = None) -> Generator[Publication, None, None]:
        '''Yields a `Publication` for each publication in the dataset.'''
        for doc in self.db.collection('publications').stream():
            yield Publication(doc.id, doc.get('count'), image_url_path(doc.id, bucket_name))

    def word_counts(self, publ: str, top_n: int = 10, checkpoint: Tuple[str, int] = None) -> Generator[WordCount, None, None]:
        '''Yields up to top_n WordCounts for the given publication.
        If a checkpoint tuple is provided, it's used as starting place for the results.
        This allows for pagination. Example:
            word_counts('vox', 10, firestore.Client(), ('apple', 30))
        The results would start from the record with the word: apple with the count of 30.
        '''
        # If it's None at the start, make it Tuple
        checkpoint = checkpoint or (None, None)
        (word, count) = checkpoint  # Unpack
        # Check the truthiness of word, check to see if count is None
        # Since count is expected to be an int, checking truthiness will fail for 0.
        # Not sure that's likely, but, it could happen...right?
        if word and count is not None:
            checkpoint = {'word': word, 'count': count}
        else:
            checkpoint = {}

        q = self.db.collection('publications').document(publ).collection('ent')
        q = q.order_by('count', direction=firestore.Query.DESCENDING)
        q = q.order_by('word')
        q = q.limit(top_n)

        if checkpoint:
            q = q.start_after(checkpoint)

        for doc in q.stream():
            yield WordCount(doc.get('word'), doc.get('count'))

    def frequencies(self, publ: str, top_n: int = 10, checkpoint: Tuple[str, int] = None) -> Dict[str, int]:
        '''Returns a dictionary containing the frequency of each key '''
        return {wc.word: wc.count for wc in self.word_counts(publ, top_n, checkpoint)}


class NoOpDataStorage():

    def __init__(self, *args, **kwargs):
        pass

    def publications(self, bucket_name: str = None) -> Generator[Publication, None, None]:
        for i in range(10):
            pub = f'pub{i}'
            yield Publication(pub, i, image_url_path(pub, bucket_name))

    def word_counts(self, publ: str, top_n: int = 10, checkpoint: Tuple[str, int] = None) -> Generator[WordCount, None, None]:
        if checkpoint is None or checkpoint == (None, None):
            checkpoint = 0
        else:
            checkpoint = checkpoint[1] + 1

        for i in range(checkpoint, 10):
            yield WordCount(f'ent{i}', i)

    def frequencies(self, publ: str, top_n: int = 10, checkpoint: Tuple[str, int] = None) -> Dict[str, int]:
        return {wc.word: wc.count for wc in self.word_counts(publ, top_n, checkpoint)}


class BlobStorage():

    def __init__(self, client: storage.Client):
        self.blob = client

    def save(self, publ: str, bucket: str, ibytes: bytes):
        publ = pub_to_url(publ)
        b = self.blob.get_bucket(bucket)
        Blob(f'{publ}.png', b).upload_from_string(ibytes, content_type='image/png')  # noqa


class NoOpBlobStorage():

    def __init__(self, *args, **kwargs):
        pass

    def save(self, *_, **__):
        pass
