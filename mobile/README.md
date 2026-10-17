# NaSCon Mobile

This Android client is intentionally dependency-light and targets Android 10
(API 29) or newer. The API address is configurable in the app and defaults to
`http://10.0.2.2:8080`.

The client keeps cached JSON and pending actions in `SharedPreferences`, uses
the Android Keystore-backed encrypted preferences for the access token, and
replays actions through `/audit/v1/offline-sync` when connectivity returns.

Build an installable debug APK with:

```sh
gradlew.bat :app:assembleDebug
```

For the competition release artifact, copy the signed output to
`mobile/release/app-release.apk`.
