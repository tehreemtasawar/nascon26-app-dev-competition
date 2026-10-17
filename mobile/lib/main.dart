import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const NasconApp());
}

class NasconApp extends StatelessWidget {
  const NasconApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'NaSCon 26 Sports Operations',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1E3A8A), // Deep Blue (Tenant Alpha Primary)
          primary: const Color(0xFF1E3A8A),
          secondary: const Color(0xFFD97706),
        ),
        useMaterial3: true,
        fontFamily: 'Roboto',
      ),
      home: const MainScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  String baseUrl = "http://10.0.2.2:8080"; // Default emulator, can change to LAN
  bool isOnline = true;
  bool isSyncing = false;
  String currentRole = "league_organizer";
  String currentUserEmail = "organizer@nascon.test";

  int _selectedTab = 0;
  List<Map<String, dynamic>> pendingQueue = [];

  // Data states
  List<dynamic> fixtures = [];
  Map<String, dynamic>? standingsData;
  Map<String, dynamic>? clubProfile;
  List<dynamic> storeProducts = [];
  bool isLoading = false;

  @override
  void initState() {
    super.initState();
    _loadLocalSettingsAndQueue();
  }

  Future<void> _loadLocalSettingsAndQueue() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      baseUrl = prefs.getString("baseUrl") ?? "http://10.0.2.2:8080";
      final queueStr = prefs.getString("pendingQueue") ?? "[]";
      pendingQueue = List<Map<String, dynamic>>.from(jsonDecode(queueStr));
    });
    _fetchData();
  }

  Future<void> _saveQueue() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString("pendingQueue", jsonEncode(pendingQueue));
  }

  Future<void> _cacheData(String key, dynamic data) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, jsonEncode(data));
  }

  Future<dynamic> _getCachedData(String key) async {
    final prefs = await SharedPreferences.getInstance();
    final str = prefs.getString(key);
    return str != null ? jsonDecode(str) : null;
  }

  Future<void> _fetchData() async {
    if (!isOnline) {
      _loadCachedDataOnly();
      return;
    }

    setState(() => isLoading = true);

    try {
      // 1. Fetch standings
      final stdResp = await http.get(Uri.parse("$baseUrl/audit/v1/standings/league-alpha-1")).timeout(const Duration(seconds: 3));
      if (stdResp.statusCode == 200) {
        final decoded = jsonDecode(stdResp.body);
        setState(() => standingsData = decoded);
        _cacheData("standings", decoded);
      }

      // 2. Fetch products
      final prodResp = await http.get(Uri.parse("$baseUrl/api/v1/store/products")).timeout(const Duration(seconds: 3));
      if (prodResp.statusCode == 200) {
        final decoded = jsonDecode(prodResp.body)["products"] ?? [];
        setState(() => storeProducts = decoded);
        _cacheData("products", decoded);
      }

      // 3. Fetch club profile
      final clubResp = await http.get(Uri.parse("$baseUrl/api/v1/clubs/club-alpha-1")).timeout(const Duration(seconds: 3));
      if (clubResp.statusCode == 200) {
        final decoded = jsonDecode(clubResp.body);
        setState(() => clubProfile = decoded);
        _cacheData("clubProfile", decoded);
      }

      // Generate default demo fixtures if not provided
      setState(() {
        fixtures = [
          {"match_id": "m1", "home": "club-alpha-1", "away": "club-alpha-2", "status": "upcoming", "time": "14:00 PKT"},
          {"match_id": "m2", "home": "club-alpha-1", "away": "club-beta-1", "status": "in_progress", "home_score": 2, "away_score": 1, "time": "Live"}
        ];
      });
      _cacheData("fixtures", fixtures);
    } catch (e) {
      // Fallback to cache if network fails
      _loadCachedDataOnly();
    } finally {
      setState(() => isLoading = false);
    }
  }

  Future<void> _loadCachedDataOnly() async {
    final cachedStd = await _getCachedData("standings");
    final cachedProd = await _getCachedData("products");
    final cachedClub = await _getCachedData("clubProfile");
    final cachedFixt = await _getCachedData("fixtures");

    setState(() {
      if (cachedStd != null) standingsData = cachedStd;
      if (cachedProd != null) storeProducts = cachedProd;
      if (cachedClub != null) clubProfile = cachedClub;
      if (cachedFixt != null) fixtures = cachedFixt;
    });
  }

  void _queueAction(String type, Map<String, dynamic> payload, int baseVersion) {
    final actionId = "act-${DateTime.now().millisecondsSinceEpoch}";
    final action = {
      "action_id": actionId,
      "type": type,
      "queued_at": DateTime.now().toUtc().toIso8601String(),
      "base_version": baseVersion,
      "payload": payload
    };

    setState(() {
      pendingQueue.add(action);
    });
    _saveQueue();

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text("Action queued offline (${pendingQueue.length} pending)"),
        backgroundColor: Colors.amber.shade800,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _syncPendingActions() async {
    if (pendingQueue.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Queue is empty. Everything up to date.")),
      );
      return;
    }

    setState(() => isSyncing = true);

    try {
      final syncBody = {
        "device_id": "flutter-mobile-client-01",
        "actions": pendingQueue
      };

      final resp = await http.post(
        Uri.parse("$baseUrl/audit/v1/offline-sync"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(syncBody),
      ).timeout(const Duration(seconds: 5));

      if (resp.statusCode == 200) {
        final resJson = jsonDecode(resp.body);
        final summary = resJson["summary"];
        final applied = summary["applied"] ?? 0;
        final rejected = summary["rejected"] ?? 0;

        setState(() {
          pendingQueue.clear();
        });
        await _saveQueue();
        await _fetchData();

        showDialog(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text("Sync Complete"),
            content: Text("Applied: $applied\nRejected: $rejected\nQueue cleared successfully."),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("OK"))
            ],
          ),
        );
      } else {
        throw Exception("Server returned ${resp.statusCode}");
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Sync failed: $e. Actions remain in queue."), backgroundColor: Colors.red),
      );
    } finally {
      setState(() => isSyncing = false);
    }
  }

  void _showSettingsDialog() {
    final controller = TextEditingController(text: baseUrl);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Server Settings"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: "Backend Host (e.g. http://10.0.2.2:8080 or LAN IP)",
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("Cancel")),
          ElevatedButton(
            onPressed: () async {
              final prefs = await SharedPreferences.getInstance();
              await prefs.setString("baseUrl", controller.text.trim());
              setState(() => baseUrl = controller.text.trim());
              Navigator.pop(ctx);
              _fetchData();
            },
            child: const Text("Save"),
          )
        ],
      ),
    );
  }

  void _showRoleLoginDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Switch Demo Account"),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _roleTile("Platform Super-Admin", "admin@nascon.test", "super_admin"),
              _roleTile("League Organizer", "organizer@nascon.test", "league_organizer"),
              _roleTile("Club Manager", "manager@nascon.test", "club_manager"),
              _roleTile("Player", "player@nascon.test", "player"),
              _roleTile("General Viewer", "viewer@nascon.test", "viewer"),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("Close")),
        ],
      ),
    );
  }

  Widget _roleTile(String title, String email, String role) {
    return ListTile(
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
      subtitle: Text(email, style: const TextStyle(fontSize: 12)),
      trailing: currentRole == role ? const Icon(Icons.check_circle, color: Colors.green) : null,
      onTap: () {
        setState(() {
          currentRole = role;
          currentUserEmail = email;
        });
        Navigator.pop(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Switched to $title ($email)")),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("NaSCon '26 Ops", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white)),
        backgroundColor: const Color(0xFF1E3A8A),
        actions: [
          // Network toggle (Airplane mode simulator for desk check)
          IconButton(
            icon: Icon(isOnline ? Icons.wifi : Icons.airplanemode_active, color: Colors.white),
            tooltip: isOnline ? "Online (Tap to toggle offline)" : "Offline (Tap to toggle online)",
            onPressed: () {
              setState(() => isOnline = !isOnline);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(isOnline ? "Network Connected" : "Switched to Offline (Airplane Mode)"),
                  duration: const Duration(seconds: 1),
                ),
              );
              _fetchData();
            },
          ),
          IconButton(
            icon: const Icon(Icons.settings, color: Colors.white),
            onPressed: _showSettingsDialog,
          ),
          IconButton(
            icon: const Icon(Icons.account_circle, color: Colors.white),
            onPressed: _showRoleLoginDialog,
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(42),
          child: Container(
            color: const Color(0xFF172554),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: isOnline ? Colors.green.shade700 : Colors.deepOrange.shade700,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      Icon(isOnline ? Icons.check_circle : Icons.offline_bolt, size: 14, color: Colors.white),
                      const SizedBox(width: 4),
                      Text(
                        isOnline ? "ONLINE" : "OFFLINE",
                        style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  "Role: ${currentRole.replaceAll('_', ' ').toUpperCase()}",
                  style: const TextStyle(color: Colors.white70, fontSize: 11),
                ),
                const Spacer(),
                if (pendingQueue.isNotEmpty)
                  GestureDetector(
                    onTap: isOnline ? _syncPendingActions : null,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.amber.shade700,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        children: [
                          if (isSyncing)
                            const SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                          else
                            const Icon(Icons.sync, size: 14, color: Colors.white),
                          const SizedBox(width: 4),
                          Text(
                            "${pendingQueue.length} PENDING - SYNC",
                            style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold),
                          ),
                        ],
                      ),
                    ),
                  )
              ],
            ),
          ),
        ),
      ),
      body: isLoading
          ? const Center(child: CircularProgressIndicator())
          : IndexedStack(
              index: _selectedTab,
              children: [
                _buildFixturesTab(),
                _buildStandingsTab(),
                _buildStoreTab(),
                _buildRosterTab(),
                _buildScoringTab(),
              ],
            ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedTab,
        onDestinationSelected: (idx) => setState(() => _selectedTab = idx),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.sports_soccer), label: 'Fixtures'),
          NavigationDestination(icon: Icon(Icons.leaderboard), label: 'Standings'),
          NavigationDestination(icon: Icon(Icons.shopping_bag), label: 'Store'),
          NavigationDestination(icon: Icon(Icons.group), label: 'Roster'),
          NavigationDestination(icon: Icon(Icons.edit_note), label: 'Scoring'),
        ],
      ),
    );
  }

  // -------------------------------------------------------------
  // 1. FIXTURES & MATCH DETAIL SCREEN
  // -------------------------------------------------------------
  Widget _buildFixturesTab() {
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: fixtures.length,
      itemBuilder: (ctx, idx) {
        final f = fixtures[idx];
        return Card(
          elevation: 2,
          margin: const EdgeInsets.symmetric(vertical: 8),
          child: ListTile(
            contentPadding: const EdgeInsets.all(16),
            leading: CircleAvatar(
              backgroundColor: Theme.of(context).primaryColor,
              child: const Icon(Icons.sports, color: Colors.white),
            ),
            title: Text(
              "${f['home']} vs ${f['away']}",
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
            ),
            subtitle: Text("Status: ${f['status']} | Time: ${f['time']}"),
            trailing: const Icon(Icons.arrow_forward_ios, size: 16),
            onTap: () => _openMatchDetail(f),
          ),
        );
      },
    );
  }

  void _openMatchDetail(Map<String, dynamic> match) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text("Match Details: ${match['match_id']}", style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const Divider(),
            Text("Teams: ${match['home']} vs ${match['away']}", style: const TextStyle(fontSize: 16)),
            Text("Status: ${match['status']}", style: const TextStyle(color: Colors.blueAccent)),
            const SizedBox(height: 16),
            const Text("Pinned Product Showcase", style: TextStyle(fontWeight: FontWeight.bold)),
            Card(
              color: Colors.amber.shade50,
              child: ListTile(
                leading: const Icon(Icons.checkroom, color: Colors.amber),
                title: const Text("Official Match Jersey (Alpha)"),
                subtitle: const Text("PKR 4500.00"),
                trailing: ElevatedButton(
                  onPressed: () {
                    Navigator.pop(ctx);
                    setState(() => _selectedTab = 2); // Switch to store
                  },
                  child: const Text("View in Store"),
                ),
              ),
            ),
            const SizedBox(height: 20),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------
  // 2. STANDINGS SCREEN (Judge Task A)
  // -------------------------------------------------------------
  Widget _buildStandingsTab() {
    if (standingsData == null || standingsData!["table"] == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.hourglass_empty, size: 48, color: Colors.grey),
            const SizedBox(height: 12),
            const Text("No Standings loaded yet"),
            ElevatedButton(onPressed: _fetchData, child: const Text("Refresh")),
          ],
        ),
      );
    }

    final table = standingsData!["table"] as List;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            "League: ${standingsData!['league_id']} (Spots: ${standingsData!['qualification_spots']})",
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: const [
                DataColumn(label: Text("Rank")),
                DataColumn(label: Text("Team")),
                DataColumn(label: Text("P")),
                DataColumn(label: Text("W")),
                DataColumn(label: Text("D")),
                DataColumn(label: Text("L")),
                DataColumn(label: Text("Diff")),
                DataColumn(label: Text("Pts")),
                DataColumn(label: Text("Status")),
              ],
              rows: table.map<DataRow>((t) {
                return DataRow(
                  cells: [
                    DataCell(Text(t["rank"].toString())),
                    DataCell(Text(t["team_id"].toString(), style: const TextStyle(fontWeight: FontWeight.bold))),
                    DataCell(Text(t["played"].toString())),
                    DataCell(Text(t["won"].toString())),
                    DataCell(Text(t["drawn"].toString())),
                    DataCell(Text(t["lost"].toString())),
                    DataCell(Text(t["diff"].toString())),
                    DataCell(Text(t["points"].toString(), style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.blue))),
                    DataCell(
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: t["status"] == "clinched"
                              ? Colors.green.shade100
                              : (t["status"] == "eliminated" ? Colors.red.shade100 : Colors.amber.shade100),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          t["status"].toString().toUpperCase(),
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                            color: t["status"] == "clinched"
                                ? Colors.green.shade800
                                : (t["status"] == "eliminated" ? Colors.red.shade800 : Colors.amber.shade900),
                          ),
                        ),
                      ),
                    ),
                  ],
                );
              }).toList(),
            ),
          )
        ],
      ),
    );
  }

  // -------------------------------------------------------------
  // 3. STORE & RECEIPT SCREEN (Judge Task B)
  // -------------------------------------------------------------
  Widget _buildStoreTab() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text("Club Merchandise Catalogue", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        Card(
          elevation: 3,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 60,
                      height: 60,
                      color: Colors.blue.shade100,
                      child: const Icon(Icons.checkroom, size: 36, color: Color(0xFF1E3A8A)),
                    ),
                    const SizedBox(width: 16),
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("Alpha Sports Jersey", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                          Text("Official Home Kit 2026", style: TextStyle(color: Colors.grey)),
                          Text("PKR 4500.00", style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.green)),
                        ],
                      ),
                    )
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    const Text("Variant: "),
                    const Chip(label: Text("Size M")),
                    const SizedBox(width: 8),
                    const Chip(label: Text("Color: Blue")),
                  ],
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: ElevatedButton.icon(
                    icon: const Icon(Icons.shopping_cart_checkout),
                    label: const Text("BUY NOW (Mock Gateway)", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF1E3A8A),
                      foregroundColor: Colors.white,
                    ),
                    onPressed: () => _executeMockCheckout("var-jersey-001-M"),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _executeMockCheckout(String variantId) async {
    final orderId = "ord-${DateTime.now().millisecondsSinceEpoch}";
    final body = {
      "order_id": orderId,
      "customer_id": "cust-mobile-user",
      "items": [{"variant_id": variantId, "quantity": 1}],
      "discount_code": null,
      "payment": {"token": "tok_success"}
    };

    if (!isOnline) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Cannot checkout while offline. Connect to network.")),
      );
      return;
    }

    try {
      final resp = await http.post(
        Uri.parse("$baseUrl/audit/v1/checkout"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );

      if (resp.statusCode == 201 || resp.statusCode == 200) {
        final resJson = jsonDecode(resp.body);
        _showReceiptDialog(resJson);
      } else {
        final err = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Checkout Error: ${err['error']['code']} - ${err['error']['message']}"), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Checkout request failed: $e")));
    }
  }

  void _showReceiptDialog(Map<String, dynamic> order) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.receipt_long, color: Colors.green),
            SizedBox(width: 8),
            Text("Order Receipt"),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text("Order ID: ${order['order_id']}", style: const TextStyle(fontWeight: FontWeight.bold)),
            Text("Status: ${order['status']}"),
            Text("Total: PKR ${((order['total_minor'] ?? 450000) / 100).toStringAsFixed(2)}"),
            const SizedBox(height: 8),
            const Text("PDF Receipt generated server-side (%PDF).", style: TextStyle(fontSize: 12, color: Colors.grey)),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("Close")),
        ],
      ),
    );
  }

  // -------------------------------------------------------------
  // 4. ROSTER MANAGEMENT SCREEN (Judge Task C: Club Manager)
  // -------------------------------------------------------------
  Widget _buildRosterTab() {
    if (currentRole != "club_manager" && currentRole != "super_admin") {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.lock, size: 48, color: Colors.grey),
              const SizedBox(height: 12),
              const Text("Roster management requires Club Manager permissions."),
              const SizedBox(height: 8),
              ElevatedButton(
                onPressed: _showRoleLoginDialog,
                child: const Text("Switch to Club Manager"),
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text("Squad & Player Operations", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        Card(
          elevation: 2,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("Quick Action: Transfer / Loan Player", style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                const Text("Player: player-alpha-1 (Ali - GK)"),
                const Text("From: sq-a -> To: sq-b"),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF1E3A8A), foregroundColor: Colors.white),
                        onPressed: () => _performRosterAction("transfer"),
                        child: const Text("Transfer Player"),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () => _performRosterAction("loan"),
                        child: const Text("Loan Player"),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _performRosterAction(String actionType) async {
    final trPayload = {
      "request_id": "tr-${DateTime.now().millisecondsSinceEpoch}",
      "league_id": "league-alpha-1",
      "player_id": "player-alpha-1",
      "type": actionType,
      "from_squad_id": "club-alpha-1",
      "to_squad_id": "club-alpha-2",
      "effective_date": "2026-09-15",
      "loan_end_date": actionType == "loan" ? "2026-10-15" : null,
      "reason": "Tactical assignment",
      "requested_by": currentUserEmail
    };

    if (!isOnline) {
      // Offline mode: queue action according to Section 5.14
      _queueAction("roster_transfer", trPayload, 1);
      return;
    }

    try {
      final resp = await http.post(
        Uri.parse("$baseUrl/audit/v1/roster/transfer"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(trPayload),
      );

      if (resp.statusCode == 201 || resp.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("$actionType completed successfully!"), backgroundColor: Colors.green),
        );
      } else {
        final err = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: ${err['error']['code']}"), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      // If network fails unexpectedly, fallback to queue
      _queueAction("roster_transfer", trPayload, 1);
    }
  }

  // -------------------------------------------------------------
  // 5. SCORING ENTRY SCREEN (League Organizer)
  // -------------------------------------------------------------
  Widget _buildScoringTab() {
    if (currentRole != "league_organizer" && currentRole != "super_admin") {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.lock, size: 48, color: Colors.grey),
              const SizedBox(height: 12),
              const Text("Scoring entry requires League Organizer permissions."),
              const SizedBox(height: 8),
              ElevatedButton(
                onPressed: _showRoleLoginDialog,
                child: const Text("Switch to League Organizer"),
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text("Match Scoring & Compensations", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        Card(
          elevation: 2,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("Active Match: m1 (Alpha 1 vs Alpha 2)", style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton.icon(
                        icon: const Icon(Icons.add),
                        label: const Text("Goal (Home)"),
                        style: ElevatedButton.styleFrom(backgroundColor: Colors.green.shade700, foregroundColor: Colors.white),
                        onPressed: () => _performScoreAction("t1", "goal"),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: ElevatedButton.icon(
                        icon: const Icon(Icons.add),
                        label: const Text("Goal (Away)"),
                        style: ElevatedButton.styleFrom(backgroundColor: Colors.green.shade700, foregroundColor: Colors.white),
                        onPressed: () => _performScoreAction("t2", "goal"),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.undo),
                    label: const Text("Disallow Goal (Compensating Event)"),
                    onPressed: _performCompensatingAction,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _performScoreAction(String teamId, String eventType) async {
    final eventPayload = {
      "event_id": "evt-${DateTime.now().millisecondsSinceEpoch}",
      "match_id": "m1",
      "type": "score",
      "payload": {
        "team_id": teamId,
        "event_type": eventType
      }
    };

    if (!isOnline) {
      _queueAction("score_event", eventPayload, 1);
      return;
    }

    try {
      final resp = await http.post(
        Uri.parse("$baseUrl/audit/v1/events"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(eventPayload),
      );

      if (resp.statusCode == 201 || resp.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Score event recorded!"), backgroundColor: Colors.green),
        );
      } else {
        final err = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: ${err['error']['code']}"), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      _queueAction("score_event", eventPayload, 1);
    }
  }

  Future<void> _performCompensatingAction() async {
    final compPayload = {
      "event_id": "evt-comp-${DateTime.now().millisecondsSinceEpoch}",
      "match_id": "m1",
      "type": "compensation",
      "payload": {
        "compensates": "evt-0001",
        "reason": "Disallowed due to offside check"
      }
    };

    if (!isOnline) {
      _queueAction("score_event", compPayload, 1);
      return;
    }

    try {
      final resp = await http.post(
        Uri.parse("$baseUrl/audit/v1/events"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(compPayload),
      );

      if (resp.statusCode == 201 || resp.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Compensating rollback event recorded!"), backgroundColor: Colors.green),
        );
      } else {
        final err = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Compensation: ${err['error']['code']}"), backgroundColor: Colors.orange),
        );
      }
    } catch (e) {
      _queueAction("score_event", compPayload, 1);
    }
  }
}
