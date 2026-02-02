```text
+---------+       NL ask        +----------+       plans        +--------------+
| Solver  |  -----------------> | Thinking | --------------->   |  Gateway     |
| (30B)   |                     |  (4B)    |                   |  Controller  |
+----+----+                     +----------+                   +-------+------+
     ^                                                                   |
     |                      results (bounded packs)                      |
     | <-------------------- Orchestrator <------------------------------+
     |                          (tools)
     |                                    doc.search / code.search / fs.read
     |                                    memory.create/query / file.create / git.commit
     |
     +---- final answer to user ------------------------------------------>
```