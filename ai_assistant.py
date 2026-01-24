"""
AI Assistant Module for TODO App
Contains all AI-related functionality including chat interface and AI model management.
"""

import json
import os
import re
import tkinter as tk
import threading
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from pathlib import Path
import shutil
import mimetypes

# Handle missing dependencies gracefully
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    print("requests not available. AI features will be limited.")
    REQUESTS_AVAILABLE = False
    requests = None

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    print("PIL/Pillow not available. Image display in AI chat will be disabled.")
    PIL_AVAILABLE = False
    Image = None
    ImageTk = None


class AIAssistant:
    def __init__(self, parent_app, ai_frame):
        self.parent_app = parent_app
        self.ai_frame = ai_frame
        
        # Check if required dependencies are available
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests library is required for AI functionality")
        
        # AI model configuration
        self.current_ai_model = ""  # Default model
        self.available_models = []
        
        # External AI provider configuration
        self.current_provider = "ollama"  # Default to local Ollama
        self.provider_config = {}
        self.load_provider_config()
        
        # Upload folder setup
        self.upload_folder = str(Path.home()) + "/TODOapp/uploads/"
        Path(self.upload_folder).mkdir(parents=True, exist_ok=True)
        
        # Check Ollama availability and models - defer to background
        self.ollama_available = False
        self.installed_models = []
        
        # Create AI widgets first (fast)
        self.create_ai_widgets()
        
        # Check Ollama status in background thread (don't block UI)
        import threading
        threading.Thread(target=self._check_ollama_and_greet, daemon=True).start()
        
    def create_ai_widgets(self):
        """Create the AI assistant interface"""
        # Chat history
        self.chat_history = ScrolledText(self.ai_frame, wrap=tk.WORD, state='disabled')
        self.chat_history.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Input row
        input_frame = ttk.Frame(self.ai_frame)
        input_frame.pack(padx=10, pady=10, fill=tk.X)
        self.upload_button = ttk.Button(input_frame, text="📎", width=3, command=self.upload_file)
        self.upload_button.pack(side=tk.LEFT, padx=5)
        self.user_input = ttk.Entry(input_frame)
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.user_input.bind("<Return>", lambda e: self.send_to_ai())
        self.send_button = ttk.Button(input_frame, text="Send", command=self.send_to_ai)
        self.send_button.pack(side=tk.RIGHT)

        # Markdown tags
        for tag, cfg in [
            ("bold",    {'font':('Helvetica',10,'bold')}),
            ("italic",  {'font':('Helvetica',10,'italic')}),
            ("header",  {'font':('Helvetica',12,'bold')}),
            ("list",    {'lmargin2':20,'spacing3':3}),
            ("code",    {'background':"#f0f0f0",'relief':'groove'}),
            ("think",   {'foreground':"gray50",'spacing1':5,'spacing3':5}),
        ]:
            self.chat_history.tag_config(tag, **cfg)

        # Skip initial greeting - will be shown after background Ollama check

    def check_ollama_status(self):
        """Check if Ollama is running and what models are installed"""
        try:
            response = requests.get('http://localhost:11434/api/tags', timeout=1)  # Reduced timeout
            if response.status_code == 200:
                self.ollama_available = True
                data = response.json()
                self.installed_models = [model['name'] for model in data.get('models', [])]
            else:
                self.ollama_available = False
        except requests.exceptions.RequestException:
            self.ollama_available = False
    
    def load_provider_config(self):
        """Load AI provider configuration from file"""
        config_file = str(Path.home()) + "/TODOapp/ai_config.json"
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    self.current_provider = config.get('provider', 'ollama')
                    self.provider_config = config.get(self.current_provider, {})
        except:
            self.current_provider = 'ollama'
            self.provider_config = {}
    
    def set_provider(self, provider, config):
        """Set the current AI provider and its configuration"""
        self.current_provider = provider
        self.provider_config = config
        # Update the greeting/status
        self.display_provider_status()
    
    def display_provider_status(self):
        """Display current provider status in chat"""
        provider_names = {
            'ollama': 'Local (Ollama)',
            'openai': 'OpenAI (ChatGPT)',
            'anthropic': 'Anthropic (Claude)',
            'google': 'Google (Gemini)'
        }
        provider_name = provider_names.get(self.current_provider, self.current_provider)
        
        if self.current_provider == 'ollama':
            if self.ollama_available and self.current_ai_model in self.installed_models:
                status = f"✓ Provider: {provider_name}\n✓ Model: {self.current_ai_model}\n"
            else:
                status = f"⚠️ Provider: {provider_name}\n⚠️ Ollama not running or model not found\n"
        else:
            model = self.provider_config.get('model', 'default')
            has_key = bool(self.provider_config.get('api_key', ''))
            if has_key:
                status = f"✓ Provider: {provider_name}\n✓ Model: {model}\n"
            else:
                status = f"⚠️ Provider: {provider_name}\n⚠️ API key not configured\n"
        
        self.update_chat_history(f"\n--- AI Provider Changed ---\n{status}")
    
    def _check_ollama_and_greet(self):
        """Background check for Ollama status then display greeting"""
        self.check_ollama_status()
        # Schedule greeting on main thread
        self.ai_frame.after(0, self.display_initial_greeting)
    
    def display_initial_greeting(self):
        """Display greeting with status information"""
        greeting = "AI: Hello! I'm your personal task assistant.\n\n"
        
        provider_names = {
            'ollama': 'Local (Ollama)',
            'openai': 'OpenAI (ChatGPT)',
            'anthropic': 'Anthropic (Claude)',
            'google': 'Google (Gemini)'
        }
        
        if self.current_provider != 'ollama':
            # Using external API
            provider_name = provider_names.get(self.current_provider, self.current_provider)
            model = self.provider_config.get('model', 'default')
            has_key = bool(self.provider_config.get('api_key', ''))
            
            if has_key:
                greeting += f"✓ Provider: {provider_name}\n"
                greeting += f"✓ Model: {model}\n"
                greeting += "How can I help you today?\n"
            else:
                greeting += f"⚠️ Provider: {provider_name}\n"
                greeting += "⚠️ API key not configured\n"
                greeting += "Please configure your API key in AI Assistant → Configure AI Provider\n"
        else:
            # Using local Ollama
            if not self.ollama_available:
                greeting += "⚠️ Status: Ollama is not running\n"
                greeting += "Please start Ollama to use AI features.\n"
                greeting += "Download from: https://ollama.ai\n"
                greeting += "\nTip: You can also use external AI services!\n"
                greeting += "Go to AI Assistant → Configure AI Provider\n"
            elif not self.installed_models:
                greeting += "⚠️ Status: No models installed\n"
                greeting += "Please install a model using:\n"
                greeting += "  ollama pull deepseek-r1:14b\n"
            elif self.current_ai_model not in self.installed_models:
                greeting += f"⚠️ Status: Model '{self.current_ai_model}' not found\n"
                greeting += f"Installed models: {', '.join(self.installed_models)}\n"
                greeting += f"Please install it using:\n"
                greeting += f"  ollama pull {self.current_ai_model}\n"
            else:
                greeting += f"✓ Status: Ready (using {self.current_ai_model})\n"
                greeting += "How can I help you today?\n"
        
        self.update_chat_history(greeting)

    def update_chat_history(self, message):
        """Update chat history with new message"""
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, message + "\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def send_to_ai(self):
        """Send user input to AI and handle response"""
        user_text = self.user_input.get()
        if not user_text:
            return
        
        # Check provider availability
        if self.current_provider == 'ollama':
            if not self.ollama_available:
                self.update_chat_history(f"User: {user_text}")
                self.update_chat_history("AI: Error - Ollama is not running. Please start Ollama first.\n"
                                        "Tip: You can use external AI services via AI Assistant → Configure AI Provider")
                return
            
            if self.current_ai_model not in self.installed_models:
                self.update_chat_history(f"User: {user_text}")
                self.update_chat_history(f"AI: Error - Model '{self.current_ai_model}' is not installed.\nRun: ollama pull {self.current_ai_model}")
                return
        else:
            # Check API key for external providers
            api_key = self.provider_config.get('api_key', '')
            if not api_key:
                self.update_chat_history(f"User: {user_text}")
                self.update_chat_history(f"AI: Error - No API key configured for {self.current_provider}.\n"
                                        "Please configure it in AI Assistant → Configure AI Provider")
                return
        
        self.update_chat_history(f"User: {user_text}")
        self.user_input.delete(0, tk.END)

        # Show "Thinking..." and store the index so we can replace it later
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, "AI: Thinking...\n", "think")
        thinking_index = self.chat_history.index("end-2l")  # Store line before last newline
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)
        
        # Disable input while processing
        self.user_input.config(state='disabled')
        self.ai_frame.config(cursor="watch")
        self.send_button.config(state='disabled')
        
        # Start processing in a separate thread based on provider
        if self.current_provider == 'ollama':
            threading.Thread(target=self.get_ai_response_ollama, args=(user_text, thinking_index)).start()
        elif self.current_provider == 'openai':
            threading.Thread(target=self.get_ai_response_openai, args=(user_text, thinking_index)).start()
        elif self.current_provider == 'anthropic':
            threading.Thread(target=self.get_ai_response_anthropic, args=(user_text, thinking_index)).start()
        elif self.current_provider == 'google':
            threading.Thread(target=self.get_ai_response_google, args=(user_text, thinking_index)).start()
        else:
            threading.Thread(target=self.get_ai_response_ollama, args=(user_text, thinking_index)).start()

    def _build_system_prompt(self):
        """Build the system prompt for AI assistants"""
        uploaded_files = [f for f in os.listdir(self.upload_folder)]
        files_context = "\nUploaded files: " + ", ".join(uploaded_files) if uploaded_files else ""
        
        return f"""You are a TODO assistant. 

Available commands (use these to manage tasks):
<command>add;[task];[date];[priority]</command>
<command>finish;[task]</command>
<command>delete;[task]</command>
<command>edit;[old task];[new task];[new date];[new priority]</command>

Current date: {datetime.now().strftime("%m-%d-%Y")}{files_context}

Help users manage their tasks. Be concise and helpful."""

    def get_ai_response_ollama(self, prompt, thinking_index):
        """Get response from local Ollama model"""
        try:
            system_prompt = self._build_system_prompt()
            
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': self.current_ai_model,
                    'prompt': f"{system_prompt}\n\nUser: {prompt}",
                    'stream': True
                },
                stream=True
            )

            # Accumulate the full response
            accumulated_response = ""
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if 'response' in chunk:
                        accumulated_response += chunk['response']

            self._finish_ai_response(accumulated_response, thinking_index)

        except requests.exceptions.ConnectionError:
            self.parent_app.root.after(0, self.update_chat_history, "AI: Could not connect to Ollama. Make sure it's running!")
        except Exception as e:
            self.parent_app.root.after(0, self.update_chat_history, f"AI: Error - {str(e)}")
        finally:
            self._reset_input_state()

    def get_ai_response_openai(self, prompt, thinking_index):
        """Get response from OpenAI API"""
        try:
            api_key = self.provider_config.get('api_key', '')
            model = self.provider_config.get('model', 'gpt-4o-mini')
            system_prompt = self._build_system_prompt()
            
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': prompt}
                    ],
                    'max_tokens': 2000
                },
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                accumulated_response = data['choices'][0]['message']['content']
                self._finish_ai_response(accumulated_response, thinking_index)
            else:
                error_msg = response.json().get('error', {}).get('message', f'HTTP {response.status_code}')
                self.parent_app.root.after(0, self.update_chat_history, f"AI: OpenAI Error - {error_msg}")
                
        except Exception as e:
            self.parent_app.root.after(0, self.update_chat_history, f"AI: Error - {str(e)}")
        finally:
            self._reset_input_state()

    def get_ai_response_anthropic(self, prompt, thinking_index):
        """Get response from Anthropic (Claude) API"""
        try:
            api_key = self.provider_config.get('api_key', '')
            model = self.provider_config.get('model', 'claude-3-5-sonnet-20241022')
            system_prompt = self._build_system_prompt()
            
            response = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': model,
                    'max_tokens': 2000,
                    'system': system_prompt,
                    'messages': [
                        {'role': 'user', 'content': prompt}
                    ]
                },
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                accumulated_response = data['content'][0]['text']
                self._finish_ai_response(accumulated_response, thinking_index)
            else:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                self.parent_app.root.after(0, self.update_chat_history, f"AI: Anthropic Error - {error_msg}")
                
        except Exception as e:
            self.parent_app.root.after(0, self.update_chat_history, f"AI: Error - {str(e)}")
        finally:
            self._reset_input_state()

    def get_ai_response_google(self, prompt, thinking_index):
        """Get response from Google Gemini API"""
        try:
            api_key = self.provider_config.get('api_key', '')
            model = self.provider_config.get('model', 'gemini-1.5-flash')
            system_prompt = self._build_system_prompt()
            
            response = requests.post(
                f'https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}',
                headers={'Content-Type': 'application/json'},
                json={
                    'contents': [
                        {'role': 'user', 'parts': [{'text': f"{system_prompt}\n\nUser: {prompt}"}]}
                    ],
                    'generationConfig': {
                        'maxOutputTokens': 2000
                    }
                },
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                accumulated_response = data['candidates'][0]['content']['parts'][0]['text']
                self._finish_ai_response(accumulated_response, thinking_index)
            else:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                self.parent_app.root.after(0, self.update_chat_history, f"AI: Google AI Error - {error_msg}")
                
        except Exception as e:
            self.parent_app.root.after(0, self.update_chat_history, f"AI: Error - {str(e)}")
        finally:
            self._reset_input_state()

    def _finish_ai_response(self, accumulated_response, thinking_index):
        """Common handler to finish AI response processing"""
        def replace_thinking():
            self.chat_history.config(state='normal')
            self.chat_history.delete(f"{thinking_index}", f"{thinking_index} lineend + 1c")
            self.chat_history.insert(tk.END, f"AI: {accumulated_response}\n")
            self.chat_history.config(state='disabled')
            self.chat_history.see(tk.END)

        self.parent_app.root.after(0, replace_thinking)
        self.parent_app.root.after(0, self.handle_ai_commands, accumulated_response)

    def _reset_input_state(self):
        """Reset input controls after AI response"""
        self.parent_app.root.after(0, lambda: self.user_input.config(state='normal'))
        self.parent_app.root.after(0, lambda: self.ai_frame.config(cursor=""))
        self.parent_app.root.after(0, lambda: self.send_button.config(state='normal'))

    def handle_ai_commands(self, full_response):
        """Extract and process AI commands from response"""
        # Extract commands from response
        command_pattern = re.compile(r'<command>(.*?)</command>', re.DOTALL)
        commands = command_pattern.findall(full_response)
        
        # Process commands silently without displaying the message again
        for cmd in commands:
            self.process_command(cmd.strip())

    def process_command(self, cmd_text):
        """Process individual AI command"""
        parts = [p.strip() for p in cmd_text.split(';')]
        if not parts:
            return

        action = parts[0].lower()
        
        try:
            if action == "add":
                task = parts[1]
                date = parts[2]
                priority = parts[3]
                self.add_task_programmatically(task, date, priority)
            elif action == "finish":
                task = parts[1]
                self.complete_task_by_name(task)
            elif action == "delete":
                task = parts[1]
                self.delete_task_by_name(task)
            elif action == "edit":
                old_task = parts[1]
                new_task = parts[2]
                new_date = parts[3]
                new_priority = parts[4]
                self.edit_task_programmatically(old_task, new_task, new_date, new_priority)
        except (IndexError, ValueError) as e:
            self.update_chat_history(f"AI: Error processing command: {str(e)}")

    def add_task_programmatically(self, task, date_str, priority_str, time_str=""):
        """Add task programmatically via AI command"""
        date = self.parent_app.parse_date(date_str)
        if not date:
            raise ValueError("Invalid date format")
        
        try:
            priority = int(priority_str)
            if not 1 <= priority <= 5:
                raise ValueError
        except ValueError:
            raise ValueError("Priority must be 1-5")

        self.parent_app.add_task(task, date, time_str, priority)
        self.update_chat_history(f"AI: Task '{task}' added successfully!")

    def complete_task_by_name(self, task_name):
        """Complete task by name via AI command"""
        tasks = self.parent_app.load_tasks()
        for t in tasks:
            if t[0] == task_name:
                tasks.remove(t)
                self.parent_app.tasks_completed += 1
                if self.parent_app.tasks_completed % 5 == 0:
                    self.parent_app.level += 1
                self.parent_app.save_character()
                self.parent_app.update_character_labels()
                self.parent_app.save_tasks(tasks)
                self.parent_app.refresh_task_list()
                self.update_chat_history(f"AI: Task '{task_name}' completed!")
                return
        raise ValueError("Task not found")

    def delete_task_by_name(self, task_name):
        """Delete task by name via AI command"""
        tasks = self.parent_app.load_tasks()
        new_tasks = [t for t in tasks if t[0] != task_name]
        if len(new_tasks) != len(tasks):
            self.parent_app.save_tasks(new_tasks)
            self.parent_app.refresh_task_list()
            self.update_chat_history(f"AI: Task '{task_name}' deleted!")
        else:
            raise ValueError("Task not found")

    def edit_task_programmatically(self, old_task_name, new_task_name, new_date_str, new_priority_str):
        """Edit task programmatically via AI command"""
        new_date = self.parent_app.parse_date(new_date_str)
        if not new_date:
            raise ValueError("Invalid new date format")
        
        try:
            new_priority = int(new_priority_str)
            if not 1 <= new_priority <= 5:
                raise ValueError
        except ValueError:
            raise ValueError("Priority must be 1-5")

        tasks = self.parent_app.load_tasks()
        for i, t in enumerate(tasks):
            if t[0] == old_task_name:
                # Preserve existing time and notes if present
                existing_time = t[2] if len(t) > 2 else ""
                existing_notes = t[4] if len(t) > 4 else (t[3] if len(t) > 3 else "No notes")
                tasks[i] = (new_task_name, new_date, existing_time, new_priority, existing_notes)
                self.parent_app.save_tasks(tasks)
                self.parent_app.refresh_task_list()
                self.update_chat_history(f"AI: Task updated successfully!")
                return
        raise ValueError("Task not found")

    def change_ai_model(self, model_name):
        """Change the AI model"""
        self.current_ai_model = model_name
        
        # Check if the new model is installed
        self.check_ollama_status()
        if model_name in self.installed_models:
            self.update_chat_history(f"System: Switched to {model_name} model ✓\n")
        else:
            self.update_chat_history(f"System: Switched to {model_name} model\n")
            self.update_chat_history(f"⚠️ Warning: Model '{model_name}' is not installed.\n")
            self.update_chat_history(f"Install it using: ollama pull {model_name}\n")

    def upload_file(self):
        """Handle file upload for AI assistant"""
        file_path = filedialog.askopenfilename(
            title="Select a file",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("Documents", "*.pdf *.doc *.docx *.txt"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            # Create a unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_filename = Path(file_path).name
            new_filename = f"{timestamp}_{original_filename}"
            new_path = Path(self.upload_folder) / new_filename
            
            # Copy file to uploads folder
            shutil.copy2(file_path, new_path)
            
            # Handle different file types
            mime_type = mimetypes.guess_type(file_path)[0]
            
            if mime_type and mime_type.startswith('image/') and PIL_AVAILABLE:
                self.display_image(new_path)
            else:
                self.display_file_link(new_filename)

    def display_image(self, image_path):
        """Display uploaded image in chat"""
        if not PIL_AVAILABLE:
            self.display_file_link(Path(image_path).name)
            return
            
        try:
            # Open and resize image
            image = Image.open(image_path)
            max_size = (300, 300)
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)
            
            # Store reference to prevent garbage collection
            if not hasattr(self, 'photo_references'):
                self.photo_references = []
            self.photo_references.append(photo)
            
            # Display in chat
            self.chat_history.config(state='normal')
            self.chat_history.insert(tk.END, "\nUser: Uploaded image:\n")
            
            # Create a label for the image and insert it
            image_label = tk.Label(self.chat_history, image=photo)
            self.chat_history.window_create(tk.END, window=image_label)
            self.chat_history.insert(tk.END, "\n")
            self.chat_history.config(state='disabled')
            self.chat_history.see(tk.END)
            
        except Exception as e:
            self.update_chat_history(f"Error displaying image: {str(e)}")

    def display_file_link(self, filename):
        """Display uploaded file link in chat"""
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, f"\nUser: Uploaded file: {filename}\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)
