# Hướng Dẫn Tích Hợp Cơ Sở Dữ Liệu SQLite Về Di Động (Mobile Integration Guide)

Tài liệu này hướng dẫn cách nhúng và truy vấn file **`english_dataset.db`** trên các nền tảng di động (iOS, Android, React Native, Flutter) đạt hiệu năng truy vấn siêu tốc (< 5ms).

---

## 1. Giới Thiệu File `english_dataset.db`

- **Định dạng:** SQLite 3 (Chế độ `WAL` - Write-Ahead Logging).
- **Dung lượng ước tính:** ~30 - 60 MB cho 20,000 từ vựng, 50,000 câu ví dụ và 1,000 bài tập phản xạ.
- **Tính chất:** File dữ liệu tĩnh Read-Only nhúng trực tiếp vào bundle ứng dụng.

---

## 2. Các Câu Lệnh SQL Truy Vấn Mẫu (Sample SQL Queries)

### A. Truy Vấn Bài Tập Phản Xạ Tốc Độ Cao (< 2.5s)
```sql
SELECT 
    r.id,
    r.drill_type,
    r.prompt_text,
    r.correct_answer,
    r.distractors_json,
    r.target_time_ms,
    s.text_en,
    s.audio_path
FROM reflex_drills r
JOIN sentences s ON r.sentence_id = s.id
WHERE s.cefr_level = 'B1' AND r.drill_type = 'speed_translation'
ORDER BY RANDOM()
LIMIT 1;
```
*Thời gian phản hồi trên thiết bị: ~1.5ms - 3.2ms.*

### B. Truy Vấn Cây Hội Thoại Rẽ Nhánh (Branching Dialogue Nodes)
```sql
SELECT 
    n.id,
    n.speaker_role,
    n.choice_label,
    s.text_en,
    s.text_vi,
    s.audio_path
FROM dialogue_nodes n
JOIN sentences s ON n.sentence_id = s.id
WHERE n.tree_id = ? AND (n.parent_node_id = ? OR (? IS NULL AND n.parent_node_id IS NULL));
```

### C. Tra Cứu Từ Vựng & Phiên Âm IPA
```sql
SELECT 
    w.lemma,
    w.pos,
    w.ipa_us,
    w.cefr_level,
    d.definition_en,
    d.definition_vi,
    d.example
FROM words w
LEFT JOIN definitions d ON w.id = d.word_id
WHERE w.lemma = 'abandon'
LIMIT 1;
```

---

## 3. Hướng Dẫn Tích Hợp Trên iOS (Swift / SwiftData / FMDB)

### Thêm File DB Vào App Bundle
1. Kéo thả file `english_dataset.db` vào Xcode project, chọn **Copy items if needed**.
2. Đảm bảo file nằm trong danh sách **Target Membership**.

### Code Mẫu Tra Cứu (Swift + SQLite3):
```swift
import Foundation
import SQLite3

class DatasetEngine {
    private var db: OpaquePointer?

    init() {
        if let path = Bundle.main.path(forResource: "english_dataset", ofType: "db") {
            if sqlite3_open_v2(path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK {
                print("Successfully opened english_dataset.db")
            }
        }
    }

    func getRandomReflexDrill(cefr: String) -> (prompt: String, answer: String, distractors: [String])? {
        let query = """
            SELECT r.prompt_text, r.correct_answer, r.distractors_json 
            FROM reflex_drills r 
            JOIN sentences s ON r.sentence_id = s.id 
            WHERE s.cefr_level = ? 
            ORDER BY RANDOM() LIMIT 1;
        """
        var statement: OpaquePointer?
        if sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK {
            sqlite3_bind_text(statement, 1, (cefr as NSString).utf8String, -1, nil)
            if sqlite3_step(statement) == SQLITE_ROW {
                let prompt = String(cString: sqlite3_column_text(statement, 0))
                let answer = String(cString: sqlite3_column_text(statement, 1))
                let distractorsJson = String(cString: sqlite3_column_text(statement, 2))
                
                let distractorsData = distractorsJson.data(using: .utf8) ?? Data()
                let distractors = (try? JSONSerialization.jsonObject(with: distractorsData) as? [String]) ?? []
                
                sqlite3_finalize(statement)
                return (prompt, answer, distractors)
            }
        }
        sqlite3_finalize(statement)
        return nil
    }
}
```

---

## 4. Hướng Dẫn Tích Hợp Trên Android (Kotlin / Room Asset)

### Thêm File DB Vào Assets
1. Đặt file vào thư mục `app/src/main/assets/databases/english_dataset.db`.

### Code Mẫu (Kotlin + Room):
```kotlin
@Database(entities = [WordEntity::class, SentenceEntity::class], version = 1)
abstract class AppDatabase : RoomDatabase() {
    companion object {
        fun getInstance(context: Context): AppDatabase {
            return Room.databaseBuilder(context, AppDatabase::class.java, "english_dataset.db")
                .createFromAsset("databases/english_dataset.db")
                .fallbackToDestructiveMigration()
                .build()
        }
    }
}
```

---

## 5. Hướng Dẫn Tích Hợp Trên Flutter (sqflite)

```dart
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';

Future<Database> openDatasetDatabase() async {
  var databasesPath = await getDatabasesPath();
  var path = join(databasesPath, "english_dataset.db");

  // Copy from asset if not exists
  if (!await File(path).exists()) {
    ByteData data = await rootBundle.load("assets/english_dataset.db");
    List<int> bytes = data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
    await File(path).writeAsBytes(bytes, flush: true);
  }

  return await openDatabase(path, readOnly: true);
}
```

---

## 6. Hướng Dẫn Tích Hợp Trên React Native (expo-sqlite)

```typescript
import * as FileSystem from 'expo-file-system';
import * as SQLite from 'expo-sqlite';
import { Asset } from 'expo-asset';

async function openDatabase() {
  const dbAsset = Asset.fromModule(require('./assets/english_dataset.db'));
  await dbAsset.downloadAsync();
  
  await FileSystem.copyAsync({
    from: dbAsset.localUri!,
    to: `${FileSystem.documentDirectory}SQLite/english_dataset.db`,
  });

  return SQLite.openDatabase('english_dataset.db');
}
```
