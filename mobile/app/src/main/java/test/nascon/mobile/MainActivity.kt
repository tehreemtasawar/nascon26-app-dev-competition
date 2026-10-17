package test.nascon.mobile

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var apiUrl: EditText
    private lateinit var status: TextView
    private lateinit var secureStore: android.content.SharedPreferences
    private lateinit var localStore: android.content.SharedPreferences

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val key = MasterKey.Builder(this).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        secureStore = EncryptedSharedPreferences.create(
            this, "secure", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
        localStore = getSharedPreferences("offline-cache", MODE_PRIVATE)
        apiUrl = EditText(this).apply { setText(localStore.getString("api", "http://10.0.2.2:8080")) }
        val email = EditText(this).apply { hint = "Email"; setText("viewer@nascon.test") }
        val password = EditText(this).apply { hint = "Password"; setText("Nascon@26") }
        status = TextView(this).apply { text = "Online status: checking..." }
        val login = Button(this).apply { text = "Sign in" }
        val fixtures = Button(this).apply { text = "Fixtures" }
        val standings = Button(this).apply { text = "Standings" }
        val sync = Button(this).apply { text = "Sync pending actions" }
        login.setOnClickListener { requestLogin(email.text.toString(), password.text.toString()) }
        fixtures.setOnClickListener { loadAndCache("/audit/v1/fixtures") }
        standings.setOnClickListener { loadAndCache("/audit/v1/standings/league-alpha-1") }
        sync.setOnClickListener { syncQueue() }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
            addView(TextView(context).apply { text = "NaSCon 26 League Hub"; textSize = 24f })
            addView(apiUrl); addView(email); addView(password); addView(login)
            addView(status); addView(fixtures); addView(standings); addView(sync)
        })
    }

    private fun requestLogin(email: String, password: String) {
        request("POST", "/api/v1/auth/login", JSONObject().put("email", email).put("password", password)) { body ->
            secureStore.edit().putString("token", JSONObject(body).getString("access_token")).apply()
            runOnUiThread { status.text = "Online: signed in" }
        }
    }

    private fun loadAndCache(path: String) {
        request("GET", path, null) { body -> localStore.edit().putString(path, body).apply(); runOnUiThread { status.text = "Online: cached $path" } }
    }

    private fun syncQueue() {
        val actions = JSONArray(localStore.getString("queue", "[]"))
        if (actions.length() == 0) { status.text = "No pending actions"; return }
        request("POST", "/audit/v1/offline-sync", JSONObject().put("device_id", "android-device").put("actions", actions)) {
            localStore.edit().putString("queue", "[]").apply()
            runOnUiThread { status.text = "Sync complete" }
        }
    }

    private fun request(method: String, path: String, payload: JSONObject?, success: (String) -> Unit) {
        worker.execute {
            try {
                val connection = URL(apiUrl.text.toString().trimEnd('/') + path).openConnection() as HttpURLConnection
                connection.requestMethod = method
                connection.setRequestProperty("Content-Type", "application/json")
                secureStore.getString("token", null)?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
                if (payload != null) { connection.doOutput = true; connection.outputStream.use { it.write(payload.toString().toByteArray()) } }
                val body = connection.inputStream.bufferedReader().use { it.readText() }
                success(body)
            } catch (error: Exception) {
                runOnUiThread { status.text = "Offline: cached data and pending queue available" }
            }
        }
    }
}
