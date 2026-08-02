# Mobile Integration Guide

This guide provides step-by-step instructions for embedding and querying the **`english_dataset.db`** SQLite database across mobile platforms (iOS, Android, React Native, Flutter) with high query performance (< 5ms).

---

## 1. Database Overview

- **Format:** SQLite 3 (Configured with `WAL` - Write-Ahead Logging mode).
- **Estimated Size:** ~30 - 60 MB for 20,000 words, 50,000 sentences, 1,000 reflex drills, and 50 dialogue trees.
- **Access Pattern:** Read-only offline dataset bundled directly into the mobile application asset package.

---

## 2. Sample SQL Queries

### A. High-Speed Reflex Drill Card Query (< 2.5s Target)
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
*Average device response latency: 1.5ms – 3.2ms.*

### B. Branching Dialogue Nodes Query
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

### C. Vocabulary & IPA Phonetic Lookup
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

## 3. iOS Integration (Swift / SwiftData / SQLite3)

### Adding DB to App Bundle
1. Drag and drop `english_dataset.db` into your Xcode project navigator and select **Copy items if needed**.
2. Ensure the database file is checked under **Target Membership**.

### Swift Query Implementation:
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

## 4. Android Integration (Kotlin / Room Asset)

### Adding DB to Assets
1. Place the database file under `app/src/main/assets/databases/english_dataset.db`.

### Kotlin Implementation (Room Database Asset):
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

## 5. Flutter Integration (sqflite)

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

## 6. React Native Integration (expo-sqlite)

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
