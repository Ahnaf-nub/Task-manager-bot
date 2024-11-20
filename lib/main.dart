import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:image_picker/image_picker.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'dart:io';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:http/http.dart' as http;

class Note {
  final String id;
  final String name;
  final String content;
  final String? imageUrl;
  final File? imageFile;
  final DateTime? createdAt;  // Added timestamp

  Note({
    required this.id,
    required this.name,
    required this.content,
    this.imageUrl,
    this.imageFile,
    this.createdAt,
  });

  // Factory constructor to create Note from Supabase JSON
  factory Note.fromJson(Map<String, dynamic> json) {
    return Note(
      id: json['id'] ?? '',
      name: json['name'] ?? '',
      content: json['content'] ?? '',
      imageUrl: json['image_url'],
      createdAt: json['created_at'] != null 
          ? DateTime.parse(json['created_at']) 
          : null,
    );
  }

  // Convert Note to JSON for Supabase
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'content': content,
      'image_url': imageUrl,
      'created_at': createdAt?.toIso8601String(),
    };
  }
}

class NotesTab extends StatefulWidget {
  const NotesTab({super.key});

  @override
  State<NotesTab> createState() => _NotesTabState();
}

class _NotesTabState extends State<NotesTab> {
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _contentController = TextEditingController();
  File? _imageFile;
  bool _isLoading = false;

  Future<void> _pickImage() async {
    try {
      final ImagePicker picker = ImagePicker();
      final XFile? image = await picker.pickImage(
        source: ImageSource.gallery,
        maxWidth: 1200,
        imageQuality: 85,
      );
      if (image != null) {
        setState(() => _imageFile = File(image.path));
      }
    } catch (e) {
      _showErrorMessage('Error picking image: $e');
    }
  }

  Future<void> _addNote() async {
    if (_nameController.text.isEmpty || _contentController.text.isEmpty) {
      _showErrorMessage('Please fill in all fields');
      return;
    }

    setState(() => _isLoading = true);
    try {
      String? imageUrl;
      if (_imageFile != null) {
        imageUrl = await _uploadImage(_imageFile!);
      }

      await supabase.from('notes').insert({
        'name': _nameController.text.trim(),
        'content': _contentController.text.trim(),
        'image_url': imageUrl,
        'user_id': supabase.auth.currentUser!.id,
        'created_at': DateTime.now().toIso8601String(),
      });

      if (mounted) {
        _resetForm();
        Navigator.pop(context);
      }
    } catch (e) {
      _showErrorMessage('Error saving note: $e');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<String?> _uploadImage(File imageFile) async {
    try {
      // Simplify path structure - remove nested 'notes' folder
      final String fileName = '${DateTime.now().millisecondsSinceEpoch}_${supabase.auth.currentUser!.id}.jpg';
      final String storagePath = fileName; // Remove nested path
      
      await supabase.storage.from('notes').upload(
        storagePath,
        imageFile,
        fileOptions: const FileOptions(
          cacheControl: '3600',
          contentType: 'image/jpeg',
          upsert: true,
        ),
      );

      // Get public URL with correct path
      final String imageUrl = supabase.storage.from('notes').getPublicUrl(storagePath);
      debugPrint('Image uploaded successfully: $imageUrl');
      return imageUrl;
    } catch (e) {
      debugPrint('Error uploading image: $e');
      return null;
    }
  }

  void _resetForm() {
    _nameController.clear();
    _contentController.clear();
    setState(() => _imageFile = null);
  }

  void _showErrorMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red),
    );
  }

  Future<void> _deleteNote(Map<String, dynamic> note) async {
    try {
      // Delete image from storage if exists
      if (note['image_url'] != null) {
        final Uri uri = Uri.parse(note['image_url']);
        final String fileName = uri.pathSegments.last;
        await supabase.storage.from('notes').remove([fileName]); // Remove nested path
      }
      
      await supabase.from('notes').delete().eq('id', note['id']);
    } catch (e) {
      _showErrorMessage('Error deleting note: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<List<Map<String, dynamic>>>(
      stream: supabase
          .from('notes')
          .stream(primaryKey: ['id'])
          .eq('user_id', supabase.auth.currentUser!.id)
          .order('created_at', ascending: false),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(child: Text('Error: ${snapshot.error}'));
        }

        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }

        final notes = snapshot.data ?? [];

        return Stack(
          children: [
            notes.isEmpty
                ? const Center(child: Text('No notes yet'))
                : ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: notes.length,
                    itemBuilder: (context, index) {
                      final note = notes[index];
                      return Card(
                        elevation: 2,
                        margin: const EdgeInsets.only(bottom: 16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ListTile(
                              title: Text(
                                note['name'],
                                style: const TextStyle(fontWeight: FontWeight.bold),
                              ),
                              trailing: IconButton(
                                icon: const Icon(Icons.delete),
                                onPressed: () => _deleteNote(note),
                              ),
                            ),
                            if (note['image_url'] != null)
                              _buildImageWidget(note['image_url']),
                            Padding(
                              padding: const EdgeInsets.all(16),
                              child: Text(note['content']),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
            Positioned(
              bottom: 16,
              right: 16,
              child: FloatingActionButton(
                onPressed: () => _showAddNoteDialog(context),
                child: const Icon(Icons.add),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildImageWidget(String? imageUrl) {
    if (imageUrl == null) return const SizedBox.shrink();
    
    return CachedNetworkImage(
      imageUrl: imageUrl,
      height: 200,
      width: double.infinity,
      fit: BoxFit.cover,
      placeholder: (context, url) => const Center(
        child: CircularProgressIndicator(),
      ),
      errorWidget: (context, url, error) {
        debugPrint('Image load error: $error for URL: $url');
        return const Center(
          child: Icon(Icons.error, color: Colors.red, size: 40),
        );
      },
    );
  }

  Future<void> _showAddNoteDialog(BuildContext context) {
    return showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add Note'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(labelText: 'Note Title'),
                textCapitalization: TextCapitalization.sentences,
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _contentController,
                decoration: const InputDecoration(labelText: 'Note Content'),
                maxLines: 3,
                textCapitalization: TextCapitalization.sentences,
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: _isLoading ? null : _pickImage,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.image),
                    const SizedBox(width: 8),
                    const Text('Add Image'),
                  ],
                ),
              ),
              if (_imageFile != null)
                Stack(
                  alignment: Alignment.topRight,
                  children: [
                    Image.file(_imageFile!, height: 100),
                    IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => setState(() => _imageFile = null),
                    ),
                  ],
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: _isLoading ? null : () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: _isLoading ? null : _addNote,
            child: _isLoading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Save'),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _nameController.dispose();
    _contentController.dispose();
    super.dispose();
  }
}
final appTheme = ThemeData(
  useMaterial3: true,
  brightness: Brightness.dark,
  colorScheme: ColorScheme.fromSeed(
    seedColor: Colors.blue,
    brightness: Brightness.dark,
  ),
  inputDecorationTheme: InputDecorationTheme(
    filled: true,
    fillColor: Colors.grey[900],
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: BorderSide.none,
    ),
    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
  ),
  elevatedButtonTheme: ElevatedButtonThemeData(
    style: ButtonStyle(
      padding: WidgetStateProperty.all(
        const EdgeInsets.symmetric(horizontal: 32, vertical: 12),
      ),
      shape: WidgetStateProperty.all(
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
  ),
);

// Removed duplicate HomePage class

class ChatMessage {
  final String text;
  final bool isUser;
  
  ChatMessage({required this.text, required this.isUser});
}

// Chat tab widget
class ChatTab extends StatefulWidget {
  const ChatTab({super.key});

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  final TextEditingController _messageController = TextEditingController();
  final List<ChatMessage> _messages = [];
  bool _isLoading = false;

  Future<void> _sendMessage() async {
    if (_messageController.text.trim().isEmpty) return;

    final userMessage = _messageController.text;
    setState(() {
      _messages.insert(0, ChatMessage(text: userMessage, isUser: true));
      _isLoading = true;
    });
    _messageController.clear();

    try {
      final content = [Content.text(userMessage)];
      final response = await model.generateContent(content);
      
      if (mounted) {
        setState(() {
          _messages.insert(0, ChatMessage(
            text: response.text ?? 'No response', 
            isUser: false
          ));
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'))
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: ListView.builder(
            reverse: true,
            padding: const EdgeInsets.all(16),
            itemCount: _messages.length,
            itemBuilder: (context, index) {
              final message = _messages[index];
              return Align(
                alignment: message.isUser 
                  ? Alignment.centerRight 
                  : Alignment.centerLeft,
                child: Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: message.isUser 
                      ? Colors.blue[100] 
                      : Colors.grey[200],
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    message.text,
                    style: const TextStyle(color: Colors.black),
                  ),
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(8.0),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _messageController,
                  decoration: const InputDecoration(
                    hintText: 'Type a message...',
                  ),
                ),
              ),
              IconButton(
                icon: _isLoading 
                  ? const CircularProgressIndicator() 
                  : const Icon(Icons.send),
                onPressed: _isLoading ? null : _sendMessage,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// Initialize services
final supabase = Supabase.instance.client;
final model = GenerativeModel(
  model: 'gemini-1.5-flash',
  apiKey: 'AIzaSyCwoFOnmT_BE1MdbgLHrIIQ1My1kwu2yws'
);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // Initialize timezone data for notifications
  tz_data.initializeTimeZones();
  
  await Supabase.initialize(
    url: 'https://vlqrrvvbcfehxdvaudrb.supabase.co',
    anonKey: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZscXJydnZiY2ZlaHhkdmF1ZHJiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzE1OTY2MzUsImV4cCI6MjA0NzE3MjYzNX0.SjwZCRMKPRqtLvVaYLTpR6hKMrGvGtoXcS77VoMaE_Q',
  );

  // Create the tasks table if it doesn't exist
  await supabase.rpc('create_tasks_table_if_not_exists').catchError((e) {
    debugPrint('Error creating tasks table: $e');
  });
  
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Task Manager',
      theme: appTheme,
      home: StreamBuilder<AuthState>(
        stream: supabase.auth.onAuthStateChange,
        builder: (context, snapshot) {
          if (snapshot.hasData && snapshot.data!.session != null) {
            return const HomePage();
          }
          return const AuthPage();
        },
      ),
    );
  }
}

class AuthPage extends StatefulWidget {
  const AuthPage({super.key});

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  bool isLogin = true;
  final emailController = TextEditingController();
  final passwordController = TextEditingController();
  final databaseService = DatabaseService();
  bool isLoading = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Logo or App Icon
                Icon(
                  Icons.task_alt,
                  size: 80,
                  color: Theme.of(context).primaryColor,
                ),
                const SizedBox(height: 32),
                Text(
                  isLogin ? 'Welcome Back!' : 'Create Account',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 24),
                // Email field
                TextField(
                  controller: emailController,
                  decoration: const InputDecoration(
                    labelText: 'Email',
                    prefixIcon: Icon(Icons.email_outlined),
                  ),
                  keyboardType: TextInputType.emailAddress,
                ),
                const SizedBox(height: 16),
                // Password field
                TextField(
                  controller: passwordController,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    prefixIcon: Icon(Icons.lock_outline),
                  ),
                  obscureText: true,
                ),
                const SizedBox(height: 24),
                // Submit button
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: isLoading ? null : () => authenticate(),
                    child: isLoading
                        ? const CircularProgressIndicator()
                        : Text(isLogin ? 'Sign In' : 'Sign Up'),
                  ),
                ),
                const SizedBox(height: 16),
                // Toggle auth mode
                TextButton(
                  onPressed: () => setState(() => isLogin = !isLogin),
                  child: Text(
                    isLogin
                        ? 'Don\'t have an account? Sign Up'
                        : 'Already have an account? Sign In',
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> authenticate() async {
    setState(() => isLoading = true);
    try {
      if (isLogin) {
        await databaseService.signIn(emailController.text, passwordController.text);
      } else {
        await databaseService.signUp(emailController.text, passwordController.text);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(e.toString()),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => isLoading = false);
      }
    }
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _currentIndex = 0;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Task Manager'),
          actions: [
            IconButton(
              icon: const Icon(Icons.logout),
              onPressed: () => DatabaseService().signOut(),
            ),
          ],
          bottom: TabBar(
            tabs: const [
              Tab(icon: Icon(Icons.list), text: 'Tasks'),
              Tab(icon: Icon(Icons.note), text: 'Notes'),
              Tab(icon: Icon(Icons.chat), text: 'Chat'),
            ],
            onTap: (index) {
              setState(() {
                _currentIndex = index;
              });
            },
          ),
        ),
        body: TabBarView(
          children: [
            const TaskList(),
            const NotesTab(),
            const ChatTab(),
          ],
        ),
        floatingActionButton: _currentIndex == 0 
          ? FloatingActionButton(
              onPressed: () => _showAddTaskDialog(context),
              child: const Icon(Icons.add),
            )
          : null,
      ),
    );
  }

  void _showAddTaskDialog(BuildContext context) {
    final titleController = TextEditingController();
    final deadlineController = TextEditingController();
    bool isLoading = false;
    
    bool isValidDate(String date) {
      try {
        if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(date)) return false;
        final parsed = DateTime.parse(date);
        final original = DateTime(parsed.year, parsed.month, parsed.day);
        return parsed == original;
      } catch (e) {
        return false;
      }
    }

    Future<void> addTask(StateSetter setDialogState) async {
      if (titleController.text.trim().isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please enter a task title')),
        );
        return;
      }

      if (!isValidDate(deadlineController.text)) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please enter a valid date in YYYY-MM-DD format')),
        );
        return;
      }

      try {
        // Set loading state
        setDialogState(() => isLoading = true);

        await supabase.from('tasks').insert({
          'name': titleController.text.trim(),
          'deadline': deadlineController.text,
          'user_id': supabase.auth.currentUser!.id,
          'created_at': DateTime.now().toIso8601String(),
        });

        if (context.mounted) {
          Navigator.pop(context);
        }
      } catch (error) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Error: ${error.toString()}')),
          );
        }
      } finally {
        if (context.mounted) {
          setDialogState(() => isLoading = false);
        }
      }
    }

    showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Add Task'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: titleController,
                decoration: const InputDecoration(labelText: 'Task Title'),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: deadlineController,
                decoration: const InputDecoration(
                  labelText: 'Deadline (YYYY-MM-DD)',
                  hintText: '2024-12-31',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: isLoading ? null : () => addTask(setDialogState),
              child: isLoading 
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Add'),
            ),
          ],
        ),
      ),
    );
  }
}

class TaskList extends StatefulWidget {
  const TaskList({super.key});

  @override
  State<TaskList> createState() => _TaskListState();
}

class _TaskListState extends State<TaskList> {
  @override
  void initState() {
    super.initState();
    _createTasksTable();
  }

  Future<void> _createTasksTable() async {
    try {
      // Create table using SQL directly in Supabase dashboard instead
      debugPrint('Tasks table should be created in Supabase dashboard');
    } catch (e) {
      debugPrint('Error: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final userId = supabase.auth.currentUser!.id;
    return StreamBuilder<List<Map<String, dynamic>>>(
      stream: supabase
          .from('tasks')
          .stream(primaryKey: ['id'])
          .eq('user_id', userId)
          .order('created_at', ascending: false),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(child: Text('Error: ${snapshot.error}'));
        }
        if (!snapshot.hasData || snapshot.data!.isEmpty) {
          return const Center(child: Text('No tasks yet'));
        }
        return ListView.builder(
          padding: const EdgeInsets.all(16),
          itemCount: snapshot.data!.length,
          itemBuilder: (context, index) {
            final task = snapshot.data![index];
            return TaskCard(task: task);
          },
        );
      },
    );
  }
}

class TaskCard extends StatelessWidget {
  final Map<String, dynamic> task;

  const TaskCard({super.key, required this.task});

  String _formatDate(String dateStr) {
    final date = DateTime.parse(dateStr);
    return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  }

  Future<void> _deleteTask(BuildContext context) async {
    try {
      await supabase
          .from('tasks')
          .delete()
          .match({
            'id': task['id'],
            'user_id': supabase.auth.currentUser!.id,
          });
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Task deleted successfully')),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error deleting task: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: ListTile(
        title: Text(task['name']),
        subtitle: Text(_formatDate(task['deadline'])),
        trailing: IconButton(
          icon: const Icon(Icons.delete),
          onPressed: () => _deleteTask(context),
        ),
      ),
    );
  }
}

class DatabaseService {
  Future<void> signIn(String email, String password) async {
    await supabase.auth.signInWithPassword(email: email, password: password);
  }

  Future<void> signUp(String email, String password) async {
    await supabase.auth.signUp(email: email, password: password);
  }

  Future<void> signOut() async {
    await supabase.auth.signOut();
  }

  Future<List<Map<String, dynamic>>> getTasks() async {
    final userId = supabase.auth.currentUser?.id;
    if (userId == null) return [];
    
    final response = await supabase
        .from('tasks')
        .select()
        .eq('user_id', userId)
        .order('created_at');
    return List<Map<String, dynamic>>.from(response);
  }

  Future<void> deleteTask(dynamic id) async {
    final userId = supabase.auth.currentUser?.id;
    if (userId == null) return;
    
    await supabase.from('tasks').delete().match({
      'id': id,
      'user_id': userId,
    });
  }

  Future<void> deleteNote(dynamic id) async {
    final userId = supabase.auth.currentUser?.id;
    if (userId == null) return;
    
    try {
      final note = await supabase
          .from('notes')
          .select('image_url')
          .eq('id', id)
          .eq('user_id', userId)
          .single();

      if (note['image_url'] != null) {
        final imageUrl = note['image_url'] as String;
        final imagePath = imageUrl.split('/').last;
        await supabase.storage.from('notes').remove(['notes/$imagePath']);
      }
      
      await supabase.from('notes').delete().match({
        'id': id,
        'user_id': userId,
      });
    } catch (e) {
      rethrow;
    }
  }
}

// Add this at the top of your file
bool isValidDate(String date) {
  try {
    final DateTime parsed = DateTime.parse(date);
    final String formatted = parsed.toString().substring(0, 10);
    return formatted == date;
  } catch (e) {
    return false;
  }
}

class AddTaskDialog extends StatefulWidget {
  const AddTaskDialog({super.key});

  @override
  State<AddTaskDialog> createState() => _AddTaskDialogState();
}

class _AddTaskDialogState extends State<AddTaskDialog> {
  final TextEditingController titleController = TextEditingController();
  final TextEditingController deadlineController = TextEditingController();
  bool _isLoading = false;

  Future<void> _addTask() async {
    if (titleController.text.trim().isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a task title')),
      );
      return;
    }

    if (!isValidDate(deadlineController.text)) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a valid date in YYYY-MM-DD format')),
      );
      return;
    }

    try {
      setState(() => _isLoading = true);

      await supabase.from('tasks').insert({
        'name': titleController.text.trim(),
        'deadline': deadlineController.text,
        'user_id': supabase.auth.currentUser!.id,
      });

      if (mounted) {
        Navigator.pop(context);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: ${error.toString()}')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add Task'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: titleController,
            decoration: const InputDecoration(labelText: 'Task Title'),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: deadlineController,
            decoration: const InputDecoration(
              labelText: 'Deadline (YYYY-MM-DD)',
              hintText: '2024-12-31',
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _isLoading ? null : _addTask,
          child: _isLoading
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Add'),
        ),
      ],
    );
  }

  @override
  void dispose() {
    titleController.dispose();
    deadlineController.dispose();
    super.dispose();
  }
}


Future<String?> uploadImageToSupabase(File imageFile, String noteId) async {
  try {
    final timestamp = DateTime.now().millisecondsSinceEpoch;
    final fileExtension = imageFile.path.split('.').last.toLowerCase();
    final fileName = '${timestamp}_$noteId.$fileExtension';
    final bytes = await imageFile.readAsBytes();

    // Upload file to the 'notes' bucket
    await Supabase.instance.client.storage
        .from('notes')
        .uploadBinary(
          fileName,
          bytes,
          fileOptions: FileOptions(
            contentType: 'image/$fileExtension',
            upsert: true,
          ),
        );

    // Get public URL
    final publicUrl = Supabase.instance.client.storage
        .from('notes')
        .getPublicUrl(fileName);
    return publicUrl;
  } catch (e) {
    return null;
  }
}

Widget buildNoteImage(String? imageUrl) {
  if (imageUrl == null || imageUrl.isEmpty) {
    return const SizedBox.shrink();
  }
  return CachedNetworkImage(
    imageUrl: imageUrl,
    httpHeaders: {
      'Accept': 'image/*',
    },
    placeholder: (context, url) => const Center(
      child: CircularProgressIndicator(),
    ),
    errorWidget: (context, url, error) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error),
            Text('Failed to load image'),
          ],
        ),
      );
    },
    fit: BoxFit.cover,
    height: 200,
    fadeInDuration: const Duration(milliseconds: 500),
  );
}

// Helper function to verify image URL
Future<bool> isImageUrlValid(String imageUrl) async {
  try {
    final response = await http.head(Uri.parse(imageUrl));
    return response.statusCode == 200;
  } catch (e) {
    return false;
  }
}