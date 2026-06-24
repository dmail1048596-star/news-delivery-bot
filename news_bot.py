import os
import sys
import argparse
import shutil
import feedparser
import requests
from google import genai
from gtts import gTTS
from mutagen.mp3 import MP3
from pydub import AudioSegment
from pydub.effects import speedup

# 定数・設定
KEYWORDS = ["生成AI", "投資", "経済", "一般教養ニュース", "宇宙開発", "ファッションとインテリア"]
RSS_FEEDS = [
    {"name": "Yahoo!ニュース（主要）", "url": "https://news.yahoo.co.jp/rss/topics/top-picks.xml"},
    {"name": "Yahoo!ニュース（経済）", "url": "https://news.yahoo.co.jp/rss/topics/business.xml"},
    {"name": "Yahoo!ニュース（IT・科学）", "url": "https://news.yahoo.co.jp/rss/topics/it.xml"},
]

OUTPUT_DIR = "public"

def fetch_news():
    """RSSフィードからニュース記事を収集する"""
    print("ニュースを収集しています...")
    articles = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:10]:  # 各フィード最新10件
                articles.append({
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.get("summary", ""),
                    "source": feed_info["name"]
                })
        except Exception as e:
            print(f"フィード取得エラー ({feed_info['name']}): {e}")
    return articles

def filter_and_summarize(articles):
    """Googleの新しいSDKを使用して、興味のあるニュースを厳選・要約する"""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("エラー: GEMINI_API_KEY が設定されていません。")
        sys.exit(1)
    
    try:
        client = genai.Client(api_key=gemini_key)
    except Exception as e:
        print(f"Geminiクライアント初期化エラー: {e}")
        sys.exit(1)

    # ニュースのテキストリストを作成
    news_list_text = ""
    for i, art in enumerate(articles):
        news_list_text += f"No.{i+1}\nタイトル: {art['title']}\n概要: {art['summary']}\nリンク: {art['link']}\n\n"

    prompt = f"""
あなたは優秀なニュース編集者です。
今日収集したニュースの一覧から、以下の【私の興味のあるキーワード】に合致する重要なニュースを最大3件〜5件厳選し、
それぞれについて「タイトル」と「100〜150文字程度のわかりやすい要約（日本語）」、そして元のニュースリンク（URL）を提示してください。
※音声で読み上げるため、タイトルと要約文は聞き取りやすい自然な日本語の話し言葉でまとめてください。

【私の興味のあるキーワード】
- {', '.join(KEYWORDS)}

ニュース一覧：
{news_list_text}

出力フォーマット（プレーンテキストで、マークダウンの太字「**」などは使用しないでください。）：

【朝のニュース要約】

■ [タイトル1]
[要約文1]
リンク: [URL1]

■ [タイトル2]
[要約文2]
リンク: [URL2]
"""

    print("Gemini APIで要約を生成中...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Gemini API実行エラー: {e}")
        sys.exit(1)

def generate_audio(text, output_dir):
    """要約テキストから音声ファイル（MP3）を生成し、1.2倍速に変換する"""
    print("音声ファイルを生成しています...")
    lines = text.split("\n")
    read_lines = []
    for line in lines:
        if line.startswith("リンク:") or "http" in line:
            continue
        read_lines.append(line)
    read_text = "\n".join(read_lines)

    os.makedirs(output_dir, exist_ok=True)
    
    # gTTSで一度普通の一時ファイルを作成
    tmp_filename = os.path.join(output_dir, "tmp_news.mp3")
    tts = gTTS(text=read_text, lang='ja')
    tts.save(tmp_filename)
    
    # pydubを使用して1.2倍速（ピッチ維持）に変換
    print("音声の速度を1.2倍に変換しています...")
    output_filename = os.path.join(output_dir, "news.mp3")
    try:
        sound = AudioSegment.from_mp3(tmp_filename)
        # speedupで1.2倍速にする（ピッチは変わらない）
        fast_sound = speedup(sound, playback_speed=1.2)
        fast_sound.export(output_filename, format="mp3")
    except Exception as e:
        print(f"速度変換エラー: {e}。通常速度のファイルを代替出力します。")
        shutil.copyfile(tmp_filename, output_filename)
    finally:
        # 一時ファイルを削除
        if os.path.exists(tmp_filename):
            os.remove(tmp_filename)
    
    # 再生時間を取得
    audio = MP3(output_filename)
    duration_ms = int(audio.info.length * 1000)
    
    duration_file = os.path.join(output_dir, "duration.txt")
    with open(duration_file, "w", encoding="utf-8") as f:
        f.write(str(duration_ms))
        
    print(f"音声生成完了: {output_filename} (長さ: {duration_ms / 1000} 秒)")
    return output_filename, duration_ms

def save_summary(text, output_dir):
    """要約テキストをファイルに保存する"""
    os.makedirs(output_dir, exist_ok=True)
    summary_file = os.path.join(output_dir, "summary.txt")
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"要約テキストを保存しました: {summary_file}")

def send_to_line(text, audio_url, duration_ms):
    """LINE Messaging API経由でメッセージと音声を送信する"""
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    line_user_id = os.getenv("LINE_USER_ID")

    if not line_token or not line_user_id:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が設定されていません。")
        sys.exit(1)

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {line_token}"
    }

    payload = {
        "to": line_user_id,
        "messages": [
            {
                "type": "text",
                "text": text
            },
            {
                "type": "audio",
                "originalContentUrl": audio_url,
                "duration": duration_ms
            }
        ]
    }

    print(f"LINEへメッセージを送信中... (音声URL: {audio_url})")
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            print("LINEへの送信が成功しました！")
        else:
            print(f"LINE送信エラー: ステータスコード {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"LINE通信エラー: {e}")

def run_generate():
    articles = fetch_news()
    if not articles:
        print("ニュース記事が収集できませんでした。")
        sys.exit(1)

    summary = filter_and_summarize(articles)
    print("\n--- 生成された要約 ---")
    print(summary)
    print("----------------------\n")

    save_summary(summary, OUTPUT_DIR)
    generate_audio(summary, OUTPUT_DIR)
    print("生成フェーズ完了。")

def run_send():
    summary_file = os.path.join(OUTPUT_DIR, "summary.txt")
    duration_file = os.path.join(OUTPUT_DIR, "duration.txt")

    if not os.path.exists(summary_file) or not os.path.exists(duration_file):
        print("エラー: 送信に必要なファイルが見つかりません。")
        sys.exit(1)

    with open(summary_file, "r", encoding="utf-8") as f:
        summary = f.read()

    with open(duration_file, "r", encoding="utf-8") as f:
        duration_ms = int(f.read().strip())

    github_repository = os.getenv("GITHUB_REPOSITORY")
    if github_repository:
        owner, repo = github_repository.split("/")
        audio_url = f"https://{owner.lower()}.github.io/{repo.lower()}/news.mp3"
    else:
        audio_url = "https://example.com/news.mp3"

    send_to_line(summary, audio_url, duration_ms)

def main():
    parser = argparse.ArgumentParser(description="LINEハイブリッド・ニュース配信ボット")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true", help="ニュースを収集し、要約と音声を生成します")
    group.add_argument("--send", action="store_true", help="生成された要約と音声をLINEに送信します")
    
    args = parser.parse_args()

    if args.generate:
        run_generate()
    elif args.send:
        run_send()

if __name__ == "__main__":
    main()
