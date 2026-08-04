import unittest
from unittest.mock import patch


with patch("storage.add_entry"), \
     patch("storage.get_ai_context"), \
     patch("storage.update_ai_context"):
    from pos_ai import _is_gif_request


class GifIntentTests(unittest.TestCase):
    def test_explicit_generation_requests_are_detected(self):
        requests = (
            "P.OS, сделай GIF из этого видео.",
            "P.OS, преврати вложение в гифку.",
            "P.OS, гифку из этих кадров собери.",
            "P.OS, convert this clip to GIF.",
        )
        for text in requests:
            with self.subTest(text=text):
                self.assertTrue(_is_gif_request(text, has_attachments=True))

    def test_attached_gif_analysis_does_not_trigger_generation(self):
        requests = (
            "P.OS, опиши этот GIF.",
            "P.OS, что меняется между кадрами гифки?",
            "P.OS, проанализируй приложенную гифку.",
            "P.OS, сделай описание этого GIF.",
            "P.OS, опиши, как меняется этот GIF. Не создавай новый файл.",
            "P.OS, ты видел эту гифку?",
            "GIF",
        )
        for text in requests:
            with self.subTest(text=text):
                self.assertFalse(_is_gif_request(text, has_attachments=True))
