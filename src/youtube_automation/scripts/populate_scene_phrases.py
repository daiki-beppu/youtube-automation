#!/usr/bin/env python3
"""Populate workflow-state.json scene_phrases for collections that lack them.

After this script runs, automation/bulk_update_localizations.py will be able
to regenerate translated localizations for each affected video.

Translations were authored to match the existing pattern of
20260322-rjn-city-collection (15 supported languages + en source).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
COLLECTIONS_DIR = ROOT / "collections" / "live"

# {collection_dir_name: {lang: phrase}}
SCENE_PHRASES: dict[str, dict[str, str]] = {
    "20260324-rjn-rainy-cafe-collection": {
        "en": "Rainy night cafe, jazz between the pages and coffee steam",
        "ja": "雨の夜のカフェ、ページとコーヒーの湯気の間に流れるジャズ",
        "ko": "비 오는 밤의 카페, 페이지와 커피 향기 사이로 흐르는 재즈",
        "es": "Café en una noche lluviosa, jazz entre páginas y vapor de café",
        "pt": "Café em noite chuvosa, jazz entre páginas e vapor de café",
        "zh-Hans": "雨夜咖啡馆，爵士飘荡在书页与咖啡香气之间",
        "zh-Hant": "雨夜咖啡館，爵士飄蕩在書頁與咖啡香氣之間",
        "fr": "Café sous la pluie nocturne, jazz entre pages et vapeur de café",
        "de": "Regnerisches Nachtcafé, Jazz zwischen Buchseiten und Kaffeedampf",
        "it": "Caffè in una notte piovosa, jazz tra pagine e vapore di caffè",
        "ru": "Кафе дождливой ночью, джаз между страниц и пара кофе",
        "id": "Kafe di malam hujan, jazz di antara halaman dan uap kopi",
        "th": "คาเฟ่คืนฝน แจ๊สลอยผ่านหน้ากระดาษและไอกาแฟ",
        "hi": "बारिश की रात का कैफ़े, पन्नों और कॉफ़ी की भाप के बीच jazz",
        "tr": "Yağmurlu gece kafesi, sayfalar ve kahve buharı arasında caz",
        "ar": "مقهى في ليلة ممطرة، جاز بين الصفحات وبخار القهوة",
    },
    "20260325-rjn-sleepless-midnight-collection": {
        "en": "Quiet rain at midnight, gentle jazz drifting into dreams",
        "ja": "真夜中の静かな雨、夢へと漂う優しいジャズ",
        "ko": "한밤의 고요한 비, 꿈속으로 스며드는 부드러운 재즈",
        "es": "Lluvia tranquila a medianoche, jazz suave deslizándose hacia los sueños",
        "pt": "Chuva calma à meia-noite, jazz suave deslizando para os sonhos",
        "zh-Hans": "午夜静雨，轻柔爵士飘入梦境",
        "zh-Hant": "午夜靜雨，輕柔爵士飄入夢境",
        "fr": "Pluie calme à minuit, jazz doux glissant vers les rêves",
        "de": "Stiller Regen um Mitternacht, sanfter Jazz treibt in Träume",
        "it": "Pioggia tranquilla a mezzanotte, jazz dolce verso i sogni",
        "ru": "Тихий полночный дождь, нежный джаз уносит в сны",
        "id": "Hujan tenang tengah malam, jazz lembut menuju mimpi",
        "th": "ฝนเงียบยามเที่ยงคืน แจ๊สนุ่มล่องสู่ความฝัน",
        "hi": "आधी रात की शांत बारिश, सपनों में बहता कोमल jazz",
        "tr": "Gece yarısı sessiz yağmur, rüyalara süzülen yumuşak caz",
        "ar": "مطر هادئ في منتصف الليل، جاز ناعم ينساب إلى الأحلام",
    },
    "20260327-rjn-midnight-blues-collection": {
        "en": "Lonely streetlamp in the rain, bittersweet jazz",
        "ja": "雨の中に佇む街灯、ほろ苦いジャズ",
        "ko": "비 속의 외로운 가로등, 쌉싸름한 재즈",
        "es": "Farola solitaria bajo la lluvia, jazz agridulce",
        "pt": "Poste solitário na chuva, jazz agridoce",
        "zh-Hans": "雨中孤独的街灯，苦甜交织的爵士",
        "zh-Hant": "雨中孤獨的街燈，苦甜交織的爵士",
        "fr": "Réverbère solitaire sous la pluie, jazz doux-amer",
        "de": "Einsame Straßenlaterne im Regen, bittersüßer Jazz",
        "it": "Lampione solitario sotto la pioggia, jazz agrodolce",
        "ru": "Одинокий фонарь под дождём, горько-сладкий джаз",
        "id": "Lampu jalan sepi di tengah hujan, jazz pahit-manis",
        "th": "เสาไฟเดียวดายกลางสายฝน แจ๊สหวานปนขม",
        "hi": "बारिश में अकेला streetlamp, कड़वा-मीठा jazz",
        "tr": "Yağmurda yalnız bir sokak lambası, buruk caz",
        "ar": "مصباح شارع وحيد في المطر، جاز حلو مرّ",
    },
    "20260328-rjn-last-ember-collection": {
        "en": "Thunder fading over a mountain cabin, jazz by the last ember",
        "ja": "山小屋の上で遠ざかる雷鳴、最後の残り火のそばで聴くジャズ",
        "ko": "산속 오두막 위로 멀어지는 천둥, 마지막 잉걸불 곁의 재즈",
        "es": "Trueno alejándose sobre una cabaña de montaña, jazz junto a la última brasa",
        "pt": "Trovão se afastando sobre uma cabana na montanha, jazz junto à última brasa",
        "zh-Hans": "山间小屋上的雷声渐远，最后余烬旁的爵士",
        "zh-Hant": "山間小屋上的雷聲漸遠，最後餘燼旁的爵士",
        "fr": "Tonnerre s'éloignant au-dessus d'un chalet, jazz auprès de la dernière braise",
        "de": "Donner verklingt über einer Berghütte, Jazz an der letzten Glut",
        "it": "Tuono che svanisce sopra un rifugio, jazz vicino all'ultima brace",
        "ru": "Гром затихает над хижиной в горах, джаз у последних углей",
        "id": "Guruh menjauh di atas pondok pegunungan, jazz di sisi bara terakhir",
        "th": "เสียงฟ้าร้องค่อยจางเหนือกระท่อมบนเขา แจ๊สข้างถ่านสุดท้าย",
        "hi": "पहाड़ी झोपड़ी पर मद्धम होती गड़गड़ाहट, अंतिम अंगारों के पास jazz",
        "tr": "Dağdaki kulübenin üzerinde uzaklaşan gök gürültüsü, son köz başında caz",
        "ar": "رعدٌ يبتعد فوق كوخ جبلي، وجاز قرب آخر جمرة",
    },
    "20260328-rjn-last-platform-collection": {
        "en": "Last train gone, jazz on an empty rainy platform",
        "ja": "最終電車が去った後、雨の無人ホームに流れるジャズ",
        "ko": "막차가 떠난 뒤, 빗속 텅 빈 플랫폼의 재즈",
        "es": "El último tren se ha ido, jazz en un andén lluvioso y vacío",
        "pt": "O último trem partiu, jazz numa plataforma chuvosa e vazia",
        "zh-Hans": "末班车开走后，雨夜空荡站台上的爵士",
        "zh-Hant": "末班車開走後，雨夜空蕩月台上的爵士",
        "fr": "Dernier train parti, jazz sur un quai pluvieux et désert",
        "de": "Der letzte Zug ist weg, Jazz auf einem regennassen, leeren Bahnsteig",
        "it": "L'ultimo treno è partito, jazz su un binario piovoso e vuoto",
        "ru": "Последний поезд ушёл, джаз на пустом дождливом перроне",
        "id": "Kereta terakhir telah berlalu, jazz di peron sepi yang basah",
        "th": "รถไฟเที่ยวสุดท้ายจากไป แจ๊สบนชานชาลาว่างเปล่าใต้ฝน",
        "hi": "आख़िरी ट्रेन जा चुकी, बारिश में सूने प्लेटफ़ॉर्म पर jazz",
        "tr": "Son tren gitti, yağmurlu boş peronda caz",
        "ar": "غادر آخر قطار، وجاز على رصيف ممطر مهجور",
    },
    "20260330-rjn-rainy-studio-collection": {
        "en": "Late night studio, jazz for hands that keep creating",
        "ja": "深夜のスタジオ、創り続ける手のためのジャズ",
        "ko": "한밤중 스튜디오, 계속 창작하는 손을 위한 재즈",
        "es": "Estudio de madrugada, jazz para manos que siguen creando",
        "pt": "Estúdio de madrugada, jazz para mãos que continuam criando",
        "zh-Hans": "深夜工作室，献给不停创作之手的爵士",
        "zh-Hant": "深夜工作室，獻給不停創作之手的爵士",
        "fr": "Studio en pleine nuit, jazz pour des mains qui créent encore",
        "de": "Studio tief in der Nacht, Jazz für Hände, die weiterschaffen",
        "it": "Studio a tarda notte, jazz per mani che continuano a creare",
        "ru": "Студия глубокой ночью, джаз для рук, что продолжают творить",
        "id": "Studio larut malam, jazz untuk tangan yang terus berkarya",
        "th": "สตูดิโอยามดึก แจ๊สสำหรับมือที่ยังคงสร้างสรรค์",
        "hi": "देर रात का studio, सृजन में लगे हाथों के लिए jazz",
        "tr": "Gece geç saatlerde stüdyo, yaratmaya devam eden eller için caz",
        "ar": "استوديو في وقت متأخر، جاز ليدين لا تكفّان عن الإبداع",
    },
    "20260331-rjn-dorm-window-collection": {
        "en": "Rain against the dorm window, jazz for the long night ahead",
        "ja": "寮の窓を打つ雨、長い夜のためのジャズ",
        "ko": "기숙사 창문에 부딪히는 비, 긴 밤을 위한 재즈",
        "es": "Lluvia contra la ventana del dormitorio, jazz para la larga noche por delante",
        "pt": "Chuva na janela do dormitório, jazz para a longa noite à frente",
        "zh-Hans": "雨打宿舍的窗，为漫长夜晚而响的爵士",
        "zh-Hant": "雨打宿舍的窗，為漫長夜晚而響的爵士",
        "fr": "Pluie sur la fenêtre du dortoir, jazz pour la longue nuit à venir",
        "de": "Regen am Wohnheimfenster, Jazz für die lange Nacht",
        "it": "Pioggia sulla finestra del dormitorio, jazz per la lunga notte",
        "ru": "Дождь по окну общежития, джаз для долгой ночи впереди",
        "id": "Hujan menerpa jendela asrama, jazz untuk malam panjang yang menanti",
        "th": "ฝนกระทบหน้าต่างหอพัก แจ๊สเพื่อค่ำคืนอันยาวนาน",
        "hi": "हॉस्टल की खिड़की पर बारिश, लंबी रात के लिए jazz",
        "tr": "Yurt penceresine vuran yağmur, uzun gece için caz",
        "ar": "مطر يقرع نافذة المسكن، جاز لليلة طويلة قادمة",
    },
    "20260331-rjn-library-after-hours-collection": {
        "en": "Hushed rain on library glass, jazz for the final chapter",
        "ja": "図書館のガラスを静かに打つ雨、最終章のためのジャズ",
        "ko": "도서관 유리창에 잔잔히 내리는 비, 마지막 장을 위한 재즈",
        "es": "Lluvia silenciosa en el cristal de la biblioteca, jazz para el último capítulo",
        "pt": "Chuva silenciosa no vidro da biblioteca, jazz para o capítulo final",
        "zh-Hans": "图书馆窗上的细雨，为最后一章而奏的爵士",
        "zh-Hant": "圖書館窗上的細雨，為最後一章而奏的爵士",
        "fr": "Pluie feutrée sur les vitres de la bibliothèque, jazz pour le dernier chapitre",
        "de": "Leiser Regen am Bibliotheksfenster, Jazz für das letzte Kapitel",
        "it": "Pioggia sommessa sui vetri della biblioteca, jazz per l'ultimo capitolo",
        "ru": "Тихий дождь по окну библиотеки, джаз для последней главы",
        "id": "Gerimis lirih di kaca perpustakaan, jazz untuk bab terakhir",
        "th": "สายฝนเบาๆ บนกระจกห้องสมุด แจ๊สสำหรับบทสุดท้าย",
        "hi": "लाइब्रेरी के शीशे पर धीमी बारिश, अंतिम अध्याय के लिए jazz",
        "tr": "Kütüphane camında yumuşak yağmur, son bölüm için caz",
        "ar": "مطر هادئ على زجاج المكتبة، جاز للفصل الأخير",
    },
    "20260401-rjn-rain-nest-collection": {
        "en": "Warm blanket, window rain, jazz fading gently into sleep",
        "ja": "あたたかな毛布、窓を伝う雨、眠りへと優しく溶けるジャズ",
        "ko": "따뜻한 담요, 창가의 빗소리, 잠 속으로 부드럽게 스며드는 재즈",
        "es": "Manta cálida, lluvia en la ventana, jazz que se desvanece suavemente en el sueño",
        "pt": "Cobertor quente, chuva na janela, jazz se dissipando suavemente no sono",
        "zh-Hans": "温暖的毛毯，窗上的雨声，缓缓融入睡眠的爵士",
        "zh-Hant": "溫暖的毛毯，窗上的雨聲，緩緩融入睡眠的爵士",
        "fr": "Couverture chaude, pluie à la fenêtre, jazz qui s'évanouit dans le sommeil",
        "de": "Warme Decke, Regen am Fenster, Jazz, der sanft in den Schlaf gleitet",
        "it": "Coperta calda, pioggia alla finestra, jazz che svanisce nel sonno",
        "ru": "Тёплое одеяло, дождь за окном, джаз, мягко уходящий в сон",
        "id": "Selimut hangat, hujan di jendela, jazz lembut menuju tidur",
        "th": "ผ้าห่มอุ่น เสียงฝนข้างหน้าต่าง แจ๊สนุ่มเลือนสู่นิทรา",
        "hi": "गर्म कंबल, खिड़की पर बारिश, नींद में धीरे-धीरे घुलता jazz",
        "tr": "Sıcak bir battaniye, pencerede yağmur, uykuya yumuşakça karışan caz",
        "ar": "بطانية دافئة، مطر على النافذة، جاز يذوب بهدوء في النوم",
    },
    "20260404-rjn-empty-gallery-collection": {
        "en": "Empty gallery after hours, jazz between rain and paintings",
        "ja": "閉館後の無人ギャラリー、雨と絵画の間に流れるジャズ",
        "ko": "폐관 후 텅 빈 갤러리, 비와 그림 사이를 흐르는 재즈",
        "es": "Galería vacía después del horario, jazz entre la lluvia y los cuadros",
        "pt": "Galeria vazia após o expediente, jazz entre a chuva e as pinturas",
        "zh-Hans": "闭馆后的空荡画廊，雨与画作之间流淌的爵士",
        "zh-Hant": "閉館後的空蕩畫廊，雨與畫作之間流淌的爵士",
        "fr": "Galerie vide après l'heure, jazz entre la pluie et les tableaux",
        "de": "Leere Galerie nach Feierabend, Jazz zwischen Regen und Gemälden",
        "it": "Galleria vuota dopo l'orario, jazz tra pioggia e dipinti",
        "ru": "Пустая галерея после закрытия, джаз между дождём и картинами",
        "id": "Galeri kosong selepas jam tutup, jazz di antara hujan dan lukisan",
        "th": "หอศิลป์เงียบเหงาหลังเวลาทำการ แจ๊สลอยระหว่างสายฝนกับภาพวาด",
        "hi": "बंद होने के बाद की सूनी गैलरी, बारिश और चित्रों के बीच jazz",
        "tr": "Mesai sonrası boş galeri, yağmur ile tablolar arasında caz",
        "ar": "معرض فارغ بعد ساعات العمل، جاز بين المطر واللوحات",
    },
    "20260404-rjn-parking-garage-collection": {
        "en": "Windshield rain on the top floor, jazz and flashcards",
        "ja": "最上階のフロントガラスに降る雨、ジャズと暗記カード",
        "ko": "꼭대기 층 차창에 내리는 비, 재즈와 단어카드",
        "es": "Lluvia sobre el parabrisas en el último piso, jazz y tarjetas de estudio",
        "pt": "Chuva no para-brisa no último andar, jazz e flashcards",
        "zh-Hans": "顶层车窗上的雨，爵士与单词卡",
        "zh-Hant": "頂層車窗上的雨，爵士與單字卡",
        "fr": "Pluie sur le pare-brise au dernier étage, jazz et fiches de révision",
        "de": "Regen auf der Windschutzscheibe im obersten Stock, Jazz und Lernkarten",
        "it": "Pioggia sul parabrezza all'ultimo piano, jazz e flashcard",
        "ru": "Дождь по лобовому стеклу на верхнем этаже, джаз и карточки для учёбы",
        "id": "Hujan di kaca depan lantai paling atas, jazz dan kartu hafalan",
        "th": "ฝนบนกระจกหน้ารถชั้นบนสุด แจ๊สและบัตรคำ",
        "hi": "टॉप फ़्लोर पर गाड़ी के शीशे पर बारिश, jazz और flashcards",
        "tr": "En üst katta ön cama yağan yağmur, caz ve kelime kartları",
        "ar": "مطر على الزجاج الأمامي في الطابق العلوي، جاز وبطاقات مذاكرة",
    },
    "20260406-rjn-midnight-jazz-lounge-collection": {
        "en": "Midnight Jazz Lounge",
        "ja": "ミッドナイト・ジャズ・ラウンジ",
        "ko": "미드나잇 재즈 라운지",
        "es": "Salón de jazz a medianoche",
        "pt": "Lounge de jazz à meia-noite",
        "zh-Hans": "午夜爵士酒廊",
        "zh-Hant": "午夜爵士酒廊",
        "fr": "Lounge jazz de minuit",
        "de": "Mitternachts-Jazz-Lounge",
        "it": "Lounge jazz di mezzanotte",
        "ru": "Полуночный джазовый лаунж",
        "id": "Lounge jazz tengah malam",
        "th": "เลานจ์แจ๊สยามเที่ยงคืน",
        "hi": "मध्यरात्रि जैज़ लाउंज",
        "tr": "Gece yarısı caz salonu",
        "ar": "صالون الجاز في منتصف الليل",
    },
}


def main() -> None:
    updated = 0
    for col, phrases in SCENE_PHRASES.items():
        ws_path = COLLECTIONS_DIR / col / "workflow-state.json"
        if not ws_path.exists():
            print(f"❌ {col}: workflow-state.json not found")
            continue
        state = json.loads(ws_path.read_text(encoding="utf-8"))
        if state.get("scene_phrases"):
            print(f"⏭️  {col}: already has scene_phrases, overwriting")
        state["scene_phrases"] = phrases
        ws_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"✅ {col}: {len(phrases)} languages")
        updated += 1
    print(f"\n{updated}/{len(SCENE_PHRASES)} collections updated")


if __name__ == "__main__":
    main()
