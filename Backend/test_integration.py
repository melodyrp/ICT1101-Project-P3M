
import unittest
from main import Controller
from unittest.mock import patch
import threading
import time


class TestIntegration(unittest.TestCase):

    def test_empty_sign_message(self):
        # create a controller without physical hardware
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # simulate an empty AI prediction
        controller.on_sign_sentence("")

        # check that no message was queued
        self.assertEqual(len(controller.pending), 0)


    
    def test_valid_sign_message(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # simulate AI recognising a sentence
        controller.on_sign_sentence("Hello")

        # check that the sentence was queued
        self.assertEqual(len(controller.pending), 1)

        # check that the correct sentence was stored
        self.assertEqual(controller.pending[0], "Hello")


    def test_undo_queued_message(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # simulate a recognised sign
        controller.on_sign_sentence("Hello")

        # confirm the message is queued
        self.assertEqual(len(controller.pending), 1)

        # simulate pressing UNDO
        controller.undo()

        # confirm the message was removed
        self.assertEqual(len(controller.pending), 0)


    def test_start_stop_captions(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # initially, captioning should be OFF
        self.assertFalse(controller.captioning.is_set())

        # simulate pressing START
        controller.start_captions()

        # captioning should now be ON
        self.assertTrue(controller.captioning.is_set())

        # simulate pressing STOP
        controller.stop_captions()

        # captioning should now be OFF
        self.assertFalse(controller.captioning.is_set())


    def test_unita_button_commands(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # simulate Unit A pressing START
        controller.on_unita_event("BTN START")
        self.assertTrue(controller.captioning.is_set())

        # simulate Unit A pressing STOP
        controller.on_unita_event("BTN STOP")
        self.assertFalse(controller.captioning.is_set())

        # simulate a sentence waiting to be spoken
        controller.on_sign_sentence("Hello")
        self.assertEqual(len(controller.pending), 1)

        # simulate Unit A pressing UNDO
        controller.on_unita_event("BTN UNDO")
        self.assertEqual(len(controller.pending), 0)

    def test_multiple_queued_sentences(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # Simulate three recognised sentences
        controller.on_sign_sentence("Hello")
        controller.on_sign_sentence("How are you?")
        controller.on_sign_sentence("Thank you")

        # Verify all three sentences are queued
        self.assertEqual(len(controller.pending), 3)

        # Verify their order
        self.assertEqual(
            list(controller.pending),
            ["Hello", "How are you?", "Thank you"]
        )

        # Undo the most recent sentence
        controller.undo()

        # Verify only the latest sentence was removed
        self.assertEqual(
            list(controller.pending),
            ["Hello", "How are you?"]
        )
    
    def test_speaker_worker(self):
        spoken_texts = []

        def fake_tts(text):
            spoken_texts.append(text)
            return b"\x80" * 1600

        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=fake_tts,
            stt=lambda: ""
        )

        with patch("main.unitb_client.send", return_value=0) as mock_send:

            worker = threading.Thread(
                target=controller.speaker_worker,
                daemon=True
            )
            worker.start()

            try:
                controller.on_sign_sentence("Hello")

                # Wait briefly for the worker to process the message
                deadline = time.monotonic() + 2

                while not mock_send.called and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertEqual(spoken_texts, ["Hello"])
                mock_send.assert_called_once()

                args, kwargs = mock_send.call_args

                self.assertEqual(args[1], "Hello")
                self.assertEqual(args[2], b"\x80" * 1600)

            finally:
                controller.running = False

                with controller.cv:
                    controller.cv.notify_all()

                worker.join(timeout=2)

    def test_unitb_connection_failure(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"\x80" * 1600,
            stt=lambda: ""
        )

        with patch(
            "main.unitb_client.send",
            side_effect=ConnectionError("Unit B disconnected")
        ) as mock_send, patch(
            "main.time.sleep",
            return_value=None
        ):

            worker = threading.Thread(
                target=controller.speaker_worker,
                daemon=True
            )
            worker.start()

            try:
                controller.on_sign_sentence("Hello")

                deadline = time.monotonic() + 2

                while mock_send.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertEqual(mock_send.call_count, 2)

            finally:
                controller.running = False

                with controller.cv:
                    controller.cv.notify_all()

                worker.join(timeout=2)

    def test_unitb_failure_caption(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"\x80" * 1600,
            stt=lambda: ""
        )

        with patch.object(controller, "_caption") as mock_caption, \
             patch("main.unitb_client.send",
                   side_effect=ConnectionError("Disconnected")) as mock_send, \
             patch("main.time.sleep", return_value=None):

            worker = threading.Thread(
                target=controller.speaker_worker,
                daemon=True
            )
            worker.start()

            try:
                controller.on_sign_sentence("Hello")

                deadline = time.monotonic() + 2

                while mock_caption.call_count == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertEqual(mock_send.call_count, 2)
                mock_caption.assert_called_once_with(
                    "Unit B not responding"
                )

            finally:
                controller.running = False

                with controller.cv:
                    controller.cv.notify_all()

                worker.join(timeout=2)

    def test_stt_pauses_during_speech(self):
        stt_calls = []

        def fake_stt():
            stt_calls.append("called")
            return "Hello"

        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=fake_stt
        )

        # Enable captions, but simulate Unit B speaking
        controller.captioning.set()
        controller.speaking.set()

        worker = threading.Thread(
            target=controller.caption_worker,
            daemon=True
        )
        worker.start()

        try:
            time.sleep(0.3)

            # STT must not run while Unit B is speaking
            self.assertEqual(stt_calls, [])

        finally:
            controller.running = False
            controller.captioning.clear()
            worker.join(timeout=2)

    def test_stt_resumes_after_speech(self):
        stt_called = threading.Event()

        def fake_stt():
            stt_called.set()
            return ""

        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=fake_stt
        )

        # Enable captions while Unit B is speaking
        controller.captioning.set()
        controller.speaking.set()

        worker = threading.Thread(
            target=controller.caption_worker,
            daemon=True
        )
        worker.start()

        try:
            # STT should remain paused
            self.assertFalse(stt_called.wait(timeout=0.3))

            # Simulate Unit B finishing playback
            controller.speaking.clear()

            # STT should resume
            self.assertTrue(stt_called.wait(timeout=2))

        finally:
            controller.running = False
            controller.captioning.clear()
            controller.speaking.set()
            worker.join(timeout=2)

    def test_stop_during_recording(self):
        recording_started = threading.Event()
        finish_recording = threading.Event()
        received_captions = []

        def fake_stt():
            recording_started.set()
            finish_recording.wait(timeout=2)
            return "This should not appear"

        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=fake_stt
        )

        # Capture captions instead of using hardware
        controller._caption = received_captions.append

        worker = threading.Thread(
            target=controller.caption_worker,
            daemon=True
        )

        worker.start()

        try:
            # Start captioning
            controller.start_captions()

            # Wait until recording begins
            self.assertTrue(recording_started.wait(timeout=2))

            # Press STOP while recording is in progress
            controller.stop_captions()

            # Allow the recording to finish
            finish_recording.set()

            # Verify no transcription was displayed
            worker.join(timeout=0.3)

            self.assertNotIn(
                "This should not appear",
                received_captions
            )

            self.assertFalse(controller.captioning.is_set())

        finally:
            controller.running = False
            finish_recording.set()
            worker.join(timeout=2)

    def test_duplicate_start_command(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # Monitor status messages sent to Unit A
        with patch.object(controller, "_status") as mock_status:

            # First START
            controller.start_captions()

            self.assertTrue(controller.captioning.is_set())
            mock_status.assert_called_once_with("LISTENING")

            # Second START
            controller.start_captions()

            # No additional status message should be sent
            self.assertEqual(mock_status.call_count, 1)

    def test_duplicate_stop_command(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        with patch.object(controller, "_status") as mock_status:

            # Enable captioning first
            controller.start_captions()
            self.assertTrue(controller.captioning.is_set())

            # First STOP
            controller.stop_captions()
            self.assertFalse(controller.captioning.is_set())

            # Second STOP
            controller.stop_captions()
            self.assertFalse(controller.captioning.is_set())

            # Only one IDLE status should be sent
            self.assertEqual(
                mock_status.call_args_list.count(
                    unittest.mock.call("IDLE")
                ),
                1
            )

            # Total: one LISTENING and one IDLE
            self.assertEqual(mock_status.call_count, 2)

    def test_status_after_speaking(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"\x80" * 1600,
            stt=lambda: ""
        )

        # Enable captions before speaking
        controller.captioning.set()

        with patch.object(controller, "_status") as mock_status, \
             patch("main.unitb_client.send", return_value=0):

            worker = threading.Thread(
                target=controller.speaker_worker,
                daemon=True
            )
            worker.start()

            try:
                controller.on_sign_sentence("Hello")

                # Wait for playback status to return to LISTENING
                deadline = time.monotonic() + 2

                while mock_status.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)

                # Status should become SPEAKING, then LISTENING
                self.assertEqual(
                    [call.args[0] for call in mock_status.call_args_list],
                    ["SPEAKING", "LISTENING"]
                )

                # Speaking flag should be cleared
                self.assertFalse(controller.speaking.is_set())

            finally:
                controller.running = False

                with controller.cv:
                    controller.cv.notify_all()

                worker.join(timeout=2)
    
    def test_status_after_speaking_captions_off(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"\x80" * 1600,
            stt=lambda: ""
        )

        with patch.object(controller, "_status") as mock_status, \
             patch("main.unitb_client.send", return_value=0):

            worker = threading.Thread(
                target=controller.speaker_worker,
                daemon=True
            )
            worker.start()

            try:
                controller.on_sign_sentence("Hello")

                deadline = time.monotonic() + 2

                while mock_status.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertEqual(
                    [call.args[0] for call in mock_status.call_args_list],
                    ["SPEAKING", "IDLE"]
                )

                self.assertFalse(controller.speaking.is_set())
                self.assertFalse(controller.captioning.is_set())

            finally:
                controller.running = False

                with controller.cv:
                    controller.cv.notify_all()

                worker.join(timeout=2)

    def test_stop_while_speaking(self):
        controller = Controller(
            unitb_ip="127.0.0.1",
            unita_ip=None,
            tts=lambda text: b"",
            stt=lambda: ""
        )

        # Initially, captions are enabled
        controller.start_captions()

        # Simulate Unit B speaking
        controller.speaking.set()

        # User presses STOP
        controller.on_unita_event("BTN STOP")

        # Captions should stop
        self.assertFalse(controller.captioning.is_set())

        # Unit B should still be speaking
        self.assertTrue(controller.speaking.is_set())


if __name__ == "__main__":
    unittest.main()
