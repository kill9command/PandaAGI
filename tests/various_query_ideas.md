1. Topic confusion / near-miss hallucination                                                          
  Ask about something where context might have related but not exact terms:                             
  - "what's the difference between a protein skimmer and a refugium?" (if you have refugium context but 
  not skimmer details)                                                                                  
  - "tell me about API vs Red Sea test kits" (tests if it researches or uses general knowledge)         
                                                                                                        
  2. Multi-goal query                                                                                   
  Test if partial success is handled correctly:                                                         
  - "find me a Syrian hamster for sale AND tell me what cage size they need"                            
  (One goal needs research, other might be informational)                                               
                                                                                                        
  3. "Search for more" vs context recall                                                                
  - Do a commerce search, then ask "can you find more from different breeders?"                         
  - Tests the Example 6b fix - should trigger fresh research, not reuse context                         
                                                                                                        
  4. Commerce with difficult vendors                                                                    
  - Try a niche product where vendors might have anti-bot or unusual page structures                    
  - Tests the WebAgent FORCE EXTRACT and vendor retry fixes                                             
                                                                                                        
  5. Explicit fact-check query                                                                          
  - "is it true that [something from a previous conversation]?"                                         
  - Tests if it validates claims vs just echoing stored context                                         
                                                                                                        
  6. Rapid topic switch                                                                                 
  - Research one topic, immediately ask about something completely different                            
  - Tests if memory.search properly handles topic shifts      