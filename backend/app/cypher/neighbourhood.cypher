// Everything within N hops of a node (F4, Graph Explorer).
// APOC's subgraphAll walks breadth-first and visits each node once, so it does
// not blow up on densely linked rings the way enumerating every path would.
// {label}/{key} come from a whitelist; depth (1-6), relationship filter and limit are parameters.
MATCH (start:{label} {{{key}: $key}})
CALL apoc.path.subgraphAll(start, {{maxLevel: $depth, relationshipFilter: $rel_filter, limit: $limit}})
YIELD nodes, relationships
RETURN start, nodes, relationships
