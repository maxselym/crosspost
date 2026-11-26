from crosspost.vk.normalize import normalize_post


def test_normalize_video_attachment():
    post = {
        "id": 138,
        "owner_id": -227892646,
        "date": 1749117209,
        "text": "Тестовая запись",
        "attachments": [
            {
                "type": "video",
                "video": {
                    "owner_id": -227892646,
                    "id": 456239081,
                    "title": "test.mp4",
                    "duration": 542,
                },
            }
        ],
    }

    result = normalize_post(post, vk_group_id=227892646)

    assert result["source_url"] == "https://vk.com/wall-227892646_138"

    assert len(result["media"]) == 1
    assert result["media"][0]["media_type"] == "video"
    assert result["media"][0]["original_url"] == "https://vk.com/video-227892646_456239081"

    assert result["media"][0]["raw_json"] == post["attachments"][0]
