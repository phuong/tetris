"""
This backend write all email content to settings.EMAIL_FILE_PATH,
It's good for developers who want to see how's the email look like at html format
"""

import threading
import datetime
from os.path import join, exists
from os import makedirs

from django.core.mail.backends.base import BaseEmailBackend
from django.utils import six
from django.conf import settings
from django.utils.text import slugify

EMAIL_FILE_PATH = join(settings.BASE_DIR, getattr(settings, 'EMAIL_FILE_PATH', 'sent_emails'))

# Add prefix to %H_%I%_%S or time format if you
# want to store all of sent emails to one receiver
EMAIL_PREFIX = getattr(settings, 'EMAIL_PREFIX', '%H_%I_%S')


class FileBackend(BaseEmailBackend):
    def __init__(self, *args, **kwargs):
        self._lock = threading.RLock()
        super(FileBackend, self).__init__(*args, **kwargs)

    def parse_email(self, msg_data):
        """
        Filter and only show html content
        :param msg_data:
        :return:
        """
        allow_write = False
        start_write = False
        out = ''
        messages = msg_data.split('\n')
        for m in messages:
            if m.startswith('Content-Type: text/html'):
                allow_write = True
                continue
            if m.startswith('Content-Transfer-Encoding'):
                start_write = True
                continue
            if m.startswith('--===='):
                continue
            if allow_write and start_write:
                out += m + '\n'
        return out

    def get_stream(self, to):
        to = ''.join(to) if isinstance(to, list) else to
        to = slugify(to.replace('@', '_')) + '.html'
        if EMAIL_PREFIX:
            to = datetime.datetime.now().strftime(EMAIL_PREFIX) + '_' + to
        if not exists(EMAIL_FILE_PATH):
            makedirs(EMAIL_FILE_PATH)
        stream = open(join(EMAIL_FILE_PATH, to), 'w')
        return stream

    def write_message(self, message):
        msg = message.message()
        msg_data = msg.as_bytes()
        if six.PY3:
            charset = msg.get_charset().get_output_charset() if msg.get_charset() else 'utf-8'
            msg_data = msg_data.decode(charset)
        stream = self.get_stream(message.to)
        stream.write('%s\n' % self.parse_email(msg_data))
        stream.flush()
        stream.close()

    def send_messages(self, email_messages):
        """Write all messages to the stream in a thread-safe way."""
        if not email_messages:
            return
        msg_count = 0
        with self._lock:
            for message in email_messages:
                self.write_message(message)
        return msg_count
