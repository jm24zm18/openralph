OpenRalph Comprehensive Fix Plan                                                            
                                                                                             
 Summary                                                                                     
                                                                                             
 Fix critical code issues, broken tool calls, add web search capability, fix feature system, 
  add Feature Orchestrator Agent, commit pending changes, and add test coverage.             
                                                                                             
 ---                                                                                         
 Phase 0: Add Feature Orchestrator Agent (NEW - HIGH PRIORITY)                               
                                                                                             
 Overview                                                                                    
                                                                                             
 Add a dedicated orchestrator agent that reads PRD/logs/tests and delegates work to          
 specialized agents.                                                                         
                                                                                             
 0.1 Create Orchestrator Agent Module                                                        
                                                                                             
 New file: openralph/openralph_cli/orchestrator.py                                           
                                                                                             
 Responsibilities:                                                                           
 - Read and parse PRD.md to understand project goals                                         
 - Read test reports (TEST_REPORT.md) to understand current state/failures                   
 - Read iteration logs to understand recent progress                                         
 - Break down work into prioritized features/tasks                                           
 - Output a structured FEATURE_PLAN.md                                                       
                                                                                             
 @dataclass                                                                                  
 class TaskItem:                                                                             
     id: str                                                                                 
     type: str  # "feature" | "bugfix" | "test" | "refactor"                                 
     title: str                                                                              
     description: str                                                                        
     priority: int  # 1=highest                                                              
     status: str  # "pending" | "in_progress" | "blocked" | "done"                           
     assigned_to: str  # "code" | "test" | "review"                                          
     blockers: list[str]  # other task IDs                                                   
                                                                                             
 def run_orchestrator(repo: Path, settings) -> list[TaskItem]:                               
     """Read PRD + logs + tests, produce prioritized task list."""                           
     prd_content = read_prd(repo)                                                            
     test_report = read_test_report(repo)                                                    
     recent_logs = read_recent_logs(repo)                                                    
                                                                                             
     # Call OpenCode with orchestrator prompt to analyze and plan                            
     plan = generate_feature_plan(prd_content, test_report, recent_logs, settings)           
                                                                                             
     # Write structured output                                                               
     write_feature_plan(repo, plan)                                                          
     return plan                                                                             
                                                                                             
 0.2 Add Orchestrator Coordination Files                                                     
                                                                                             
 New files in .ralph/:                                                                       
 - FEATURE_PLAN.md - Structured breakdown from orchestrator                                  
 - TASK_STATUS.json - Machine-readable task tracking                                         
                                                                                             
 FEATURE_PLAN.md format:                                                                     
 # Feature Plan                                                                              
 Generated: 2026-02-03 17:30:00                                                              
                                                                                             
 ## Priority 1: Fix Jest ES6 Module Compatibility                                            
 - **Type:** bugfix                                                                          
 - **Status:** pending                                                                       
 - **Assigned:** code                                                                        
 - **Description:** Jest can't run ES6 tests due to missing config                           
                                                                                             
 ## Priority 2: Implement Score Display                                                      
 - **Type:** feature                                                                         
 - **Status:** blocked                                                                       
 - **Blockers:** [Priority 1]                                                                
 - **Assigned:** code                                                                        
 - **Description:** Add score display per PRD requirements                                   
                                                                                             
 0.3 Integrate Orchestrator into Loop                                                        
                                                                                             
 File: openralph/openralph_cli/loop.py                                                       
                                                                                             
 New flow (sequential handoff):                                                              
 1. [ORCHESTRATOR] Read PRD + logs + test reports                                            
 2. [ORCHESTRATOR] Generate/update FEATURE_PLAN.md with prioritized tasks                    
 3. [ORCHESTRATOR] Pick highest priority non-blocked task                                    
 4. [BUILDER] Implement the task (single task focus)                                         
 5. [TEST] Run tests, update TEST_REPORT.md                                                  
 6. [REVIEW] Check PRD alignment for this task                                               
 7. [ORCHESTRATOR] Mark task done/failed, update FEATURE_PLAN.md                             
 8. Loop back to step 3 for next task                                                        
                                                                                             
 Sequential handoff ensures:                                                                 
 - One task at a time for clear progress tracking                                            
 - Test results inform next task priority                                                    
 - Failures can be re-prioritized as bugfix tasks                                            
                                                                                             
 Add orchestrator stage before builder:                                                      
 # Before each iteration                                                                     
 if settings.orchestrator_enabled:                                                           
     current_task = run_orchestrator_iteration(repo, settings)                               
     if current_task is None:                                                                
         log.info("No remaining tasks - all done!")                                          
         break                                                                               
     iter_prompt = build_task_prompt(current_task, feature_ctx)                              
                                                                                             
 0.4 Add Orchestrator Settings                                                               
                                                                                             
 File: openralph/openralph_cli/settings.py                                                   
 # Orchestrator settings (DEFAULT ON when PRD exists)                                        
 orchestrator_enabled: bool = True  # Auto-enable if docs/PRD.md exists                      
 orchestrator_replan_every: int = 3  # Re-analyze PRD every N iterations                     
 orchestrator_max_tasks: int = 10  # Max tasks to plan at once                               
                                                                                             
 Auto-detection logic:                                                                       
 - If docs/PRD.md exists → orchestrator mode enabled by default                              
 - If no PRD → fall back to direct prompt mode (legacy behavior)                             
 - User can override with --no-orchestrator flag                                             
                                                                                             
 0.5 Add CLI Commands for Orchestrator                                                       
                                                                                             
 File: openralph/openralph_cli/cli.py                                                        
 @agents_app.command("plan")                                                                 
 def agents_plan(repo: Path):                                                                
     """Run orchestrator to analyze PRD and create feature plan."""                          
                                                                                             
 @agents_app.command("status")                                                               
 def agents_status(repo: Path):                                                              
     """Show current task status from FEATURE_PLAN.md."""                                    
                                                                                             
 @agents_app.command("next")                                                                 
 def agents_next(repo: Path):                                                                
     """Show next task to be worked on."""                                                   
                                                                                             
 0.6 Orchestrator Prompt Template                                                            
                                                                                             
 New file: openralph/templates/orchestrator-prompt.md                                        
 You are the Feature Orchestrator Agent.                                                     
                                                                                             
 ## Your Inputs                                                                              
 - PRD: {prd_content}                                                                        
 - Recent Test Report: {test_report}                                                         
 - Recent Logs: {log_summary}                                                                
 - Current Feature Plan: {current_plan}                                                      
                                                                                             
 ## Your Task                                                                                
 1. Analyze the PRD to understand all required features                                      
 2. Review test failures to identify bugs needing fixes                                      
 3. Review logs to understand what's been attempted                                          
 4. Create/update a prioritized task list                                                    
                                                                                             
 ## Output Format                                                                            
 Output a JSON array of tasks:                                                               
 ```json                                                                                     
 [                                                                                           
   {                                                                                         
     "id": "task-1",                                                                         
     "type": "bugfix",                                                                       
     "title": "Fix Jest ES6 module config",                                                  
     "priority": 1,                                                                          
     "assigned_to": "code",                                                                  
     "description": "Add jest.config.js with ES6 support"                                    
   }                                                                                         
 ]                                                                                           
                                                                                             
 ---                                                                                         
                                                                                             
 ## Phase 1: Fix Critical Code Issues                                                        
                                                                                             
 ### 1.1 Fix Embedding Error Propagation (CRITICAL)                                          
 **File:** `openralph/openralph_cli/memory/index.py:171-176`                                 
 **Problem:** Single embedding failure crashes entire indexing (contradicts "best-effort")   
 **Fix:** Catch embedding errors and skip that chunk instead of re-raising                   
 ```python                                                                                   
 except Exception as e:                                                                      
     log.warning("Failed to embed chunk %s#%d: %s", c.path, c.chunk_index, e)                
     continue  # Skip this chunk, don't halt indexing                                        
                                                                                             
 1.2 Fix PRD "auto-then-handoff" Mode (CRITICAL)                                             
                                                                                             
 File: openralph/openralph_cli/loop.py:675-685                                               
 Problem: Hardcodes "No PRD changes requested" instead of waiting for human                  
 Fix: Only auto-respond when mode is "auto", not "auto-then-handoff"                         
                                                                                             
 1.3 Add Config Validation                                                                   
                                                                                             
 File: openralph/openralph_cli/settings.py                                                   
 Add validation in load() method:                                                            
 - chunk_overlap < chunk_chars (prevent infinite loops)                                      
 - Boost factors > 0 (prevent silent zeroing)                                                
                                                                                             
 ---                                                                                         
 Phase 2: Fix Broken Tool Calls                                                              
                                                                                             
 2.1 Fix Glob Tool in loop.py (BROKEN)                                                       
                                                                                             
 File: openralph/openralph_cli/loop.py:370-371                                               
 Problem: Glob calls print_tree() instead of actual glob matching                            
 Fix: Implement proper _repo_browser_glob() function like in prd.py                          
                                                                                             
 2.2 Add Result Capping in loop.py                                                           
                                                                                             
 File: openralph/openralph_cli/loop.py:431                                                   
 Problem: No cap on tool result file size (prd.py caps at 50KB)                              
 Fix: Add _cap_tool_result(result, limit=50000) before writing                               
                                                                                             
 2.3 Unify Control Flow                                                                      
                                                                                             
 File: openralph/openralph_cli/prd.py:340-400                                                
 Problem: Uses if/if/if instead of if/elif/elif (could execute multiple handlers)            
 Fix: Convert to elif chain for consistent behavior                                          
                                                                                             
 ---                                                                                         
 Phase 3: Add Web Search Capability                                                          
                                                                                             
 3.1 Add Web Search Settings                                                                 
                                                                                             
 File: openralph/openralph_cli/settings.py                                                   
 web_search_enabled: bool = False                                                            
 web_search_provider: str = "duckduckgo"  # "duckduckgo" (free) or "tavily" (requires API    
 key)                                                                                        
 tavily_api_key: str = ""  # Optional: for Tavily provider                                   
                                                                                             
 3.2 Add Web Search Permission                                                               
                                                                                             
 File: openralph/openralph_cli/opencode_config.py                                            
 - Add "web_search" to permission types                                                      
 - Add to code agent permissions (full capability agent)                                     
                                                                                             
 3.3 Implement Web Search Handler                                                            
                                                                                             
 File: openralph/openralph_cli/loop.py:373                                                   
 Replace error message with actual search:                                                   
 elif tool == "search":                                                                      
     if settings.web_search_enabled:                                                         
         result = web_search(args.get("query", ""), settings)                                
     else:                                                                                   
         result = "[error] Web search not enabled. Set web_search_enabled=true in config."   
                                                                                             
 3.4 Create Web Search Module                                                                
                                                                                             
 New file: openralph/openralph_cli/web_search.py                                             
                                                                                             
 DuckDuckGo (default, no API key):                                                           
 - Use duckduckgo-search library                                                             
 - Returns top 5 results with title, URL, snippet                                            
 - Free, no rate limits                                                                      
                                                                                             
 Tavily (optional upgrade):                                                                  
 - Use tavily-python library                                                                 
 - AI-optimized results with better relevance                                                
 - Requires tavily_api_key in config                                                         
 - Returns structured answer + sources                                                       
                                                                                             
 def web_search(query: str, settings) -> str:                                                
     if settings.web_search_provider == "tavily" and settings.tavily_api_key:                
         return _tavily_search(query, settings.tavily_api_key)                               
     return _duckduckgo_search(query)                                                        
                                                                                             
 3.5 Add Dependencies                                                                        
                                                                                             
 File: pyproject.toml                                                                        
 dependencies = [                                                                            
     ...                                                                                     
     "duckduckgo-search>=6.0.0",  # Free web search                                          
 ]                                                                                           
                                                                                             
 [project.optional-dependencies]                                                             
 tavily = ["tavily-python>=0.3.0"]  # Optional AI-optimized search                           
                                                                                             
 ---                                                                                         
 Phase 4: Fix Feature System                                                                 
                                                                                             
 4.1 Re-fetch feature_ctx Before Review (HIGH)                                               
                                                                                             
 File: openralph/openralph_cli/loop.py:930                                                   
 Problem: Review stage uses stale feature context                                            
 Fix: Add feature_ctx = get_feature_context(repo) before review prompt construction          
                                                                                             
 4.2 Inject Feature Context into Test Agent (MEDIUM)                                         
                                                                                             
 File: openralph/openralph_cli/loop.py:852-884                                               
 Problem: Test agent doesn't know about feature's test plan                                  
 Fix: Add {feature} placeholder and inject feature_ctx                                       
                                                                                             
 4.3 Boost Current Feature in Memory Query (MEDIUM)                                          
                                                                                             
 File: openralph/openralph_cli/loop.py:757-765                                               
 Problem: All features get same 1.2x boost                                                   
 Fix: If current feature set, boost its folder at 1.5x                                       
                                                                                             
 4.4 Clean Up Unused Paths Fields                                                            
                                                                                             
 File: openralph/openralph_cli/paths.py:14-15                                                
 Problem: current_feature and features_dir defined but never used                            
 Fix: Remove or integrate with features.py                                                   
                                                                                             
 ---                                                                                         
 Phase 5: Commit Pending Changes                                                             
                                                                                             
 5.1 Review Modified Files                                                                   
                                                                                             
 - docs/ARCHITECTURE.md - loop description update                                            
 - docs/USAGE.md - added Run Loop section                                                    
 - openralph/openralph_cli/cli.py - command updates                                          
 - openralph/openralph_cli/loop.py - major orchestration changes                             
 - openralph/openralph_cli/prd.py - repo browser shim                                        
 - openralph/openralph_cli/settings.py - new settings                                        
 - openralph/openralph_cli/opencode_config.py - config updates                               
 - And 7 more files...                                                                       
                                                                                             
 5.2 Add Untracked Test File                                                                 
                                                                                             
 git add tests/test_memory_query_boosts.py                                                   
                                                                                             
 5.3 Create Atomic Commits                                                                   
                                                                                             
 1. "Fix critical embedding and PRD handoff issues"                                          
 2. "Fix glob tool and add result capping"                                                   
 3. "Add web search capability for agents"                                                   
 4. "Fix feature context injection in loop stages"                                           
 5. "Update docs and add test coverage"                                                      
                                                                                             
 ---                                                                                         
 Phase 6: Add Test Coverage                                                                  
                                                                                             
 6.1 Priority Test Files to Create                                                           
                                                                                             
 tests/test_cli.py - CLI command integration tests                                           
 - Test init, doctor, run commands                                                           
 - Test config commands                                                                      
 - Test memory commands                                                                      
                                                                                             
 tests/test_settings.py - Config loading tests                                               
 - Test config merge precedence                                                              
 - Test validation (new)                                                                     
 - Test env var overrides                                                                    
                                                                                             
 tests/test_prd.py - PRD generation tests                                                    
 - Test context collection                                                                   
 - Test repo browser tool execution                                                          
 - Test JSON parsing edge cases                                                              
                                                                                             
 tests/test_features.py - Feature system tests                                               
 - Test feature creation                                                                     
 - Test current feature tracking                                                             
 - Test context generation                                                                   
                                                                                             
 tests/test_git_manager.py - Git operations tests                                            
 - Test branch creation/checkout                                                             
 - Test checkpoint commits                                                                   
 - Test rollback logic                                                                       
                                                                                             
 6.2 Test Fixtures to Add                                                                    
                                                                                             
 - Mock Ollama responses                                                                     
 - Mock OpenCode subprocess                                                                  
 - Temporary git repos                                                                       
                                                                                             
 ---                                                                                         
 Verification Plan                                                                           
                                                                                             
 After Each Phase:                                                                           
                                                                                             
 1. Run existing tests: pytest tests/                                                        
 2. Run type checker: mypy openralph/                                                        
 3. Test manually with testpong repo                                                         
                                                                                             
 End-to-End Verification:                                                                    
                                                                                             
 # Test init                                                                                 
 openralph init /tmp/test-repo                                                               
                                                                                             
 # Test memory                                                                               
 openralph memory index /tmp/test-repo                                                       
 openralph memory query /tmp/test-repo "test query"                                          
                                                                                             
 # Test feature system                                                                       
 openralph feature new /tmp/test-repo "Test Feature"                                         
 openralph feature current /tmp/test-repo                                                    
                                                                                             
 # Test orchestrator (NEW)                                                                   
 openralph agents plan /tmp/test-repo      # Generate feature plan from PRD                  
 openralph agents status /tmp/test-repo    # Show task status                                
 openralph agents next /tmp/test-repo      # Show next task                                  
                                                                                             
 # Test run loop with orchestrator                                                           
 openralph run /tmp/test-repo "Implement the PRD" --orchestrator --max-iters 3               
                                                                                             
 # Test run loop (quick iteration, legacy mode)                                              
 openralph run /tmp/test-repo "Add hello world" --max-iters 1                                
                                                                                             
 Orchestrator-Specific Tests:                                                                
                                                                                             
 1. Create a repo with PRD.md                                                                
 2. Run openralph agents plan - verify FEATURE_PLAN.md created                               
 3. Add failing tests                                                                        
 4. Run openralph agents plan again - verify bugfix tasks added                              
 5. Run full loop - verify tasks completed in priority order                                 
                                                                                             
 ---                                                                                         
 Files to Modify                                                                             
 File: memory/index.py                                                                       
 Changes: Fix embedding error handling                                                       
 ────────────────────────────────────────                                                    
 File: loop.py                                                                               
 Changes: Fix PRD handoff, glob tool, feature context, integrate orchestrator                
 ────────────────────────────────────────                                                    
 File: settings.py                                                                           
 Changes: Add validation, web search settings, orchestrator settings                         
 ────────────────────────────────────────                                                    
 File: opencode_config.py                                                                    
 Changes: Add web search permission                                                          
 ────────────────────────────────────────                                                    
 File: prd.py                                                                                
 Changes: Unify control flow                                                                 
 ────────────────────────────────────────                                                    
 File: paths.py                                                                              
 Changes: Add orchestrator paths, clean up unused fields                                     
 ────────────────────────────────────────                                                    
 File: cli.py                                                                                
 Changes: Add orchestrator CLI commands                                                      
 ────────────────────────────────────────                                                    
 File: orchestrator.py                                                                       
 Changes: NEW - orchestrator agent implementation                                            
 ────────────────────────────────────────                                                    
 File: web_search.py                                                                         
 Changes: NEW - web search implementation                                                    
 ────────────────────────────────────────                                                    
 File: templates/orchestrator-prompt.md                                                      
 Changes: NEW - orchestrator prompt template                                                 
 ────────────────────────────────────────                                                    
 File: tests/test_*.py                                                                       
 Changes: NEW - comprehensive tests                             
