-- Batch operations for reducing call overhead and optimizing budget efficiency
-- DYNAMIC
-- Supports: move, place, remove, inventory_add, inventory_remove, inspect, teleport
-- Args: {"operations": [...], "stop_on_error": true, "transaction": false}
-- Returns: {"ok": true, "results": [...], "success_count": N, "failed_count": M}

return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Get agent once for all operations
    local player = game.players[1]
    if not player or not player.character then
        return serialize({ok = false, error = "no player character"})
    end
    
    local character = player.character
    local surface = character.surface
    local force = character.force
    local inventory = character.get_inventory(defines.inventory.character_main)
    
    local operations = args.operations or {}
    local stop_on_error = args.stop_on_error ~= false  -- default true
    local transaction = args.transaction or false
    
    local results = {}
    local success_count = 0
    local failed_count = 0
    local rollback_data = {}
    
    -- Helper: distance calculation
    local function distance(p1, p2)
        local dx = p1.x - p2.x
        local dy = p1.y - p2.y
        return math.sqrt(dx * dx + dy * dy)
    end
    
    -- Helper: parse position from args
    local function get_position(op)
        if op.x and op.y then
            return {x = tonumber(op.x), y = tonumber(op.y)}
        end
        return nil
    end
    
    -- Helper: direction mapping
    local DIR_MAP = {
        [0] = defines.direction.north,
        [1] = defines.direction.east,
        [2] = defines.direction.south,
        [3] = defines.direction.west,
        north = defines.direction.north,
        east = defines.direction.east,
        south = defines.direction.south,
        west = defines.direction.west,
    }
    
    -- Execute single operation
    local function execute_op(op, index)
        local op_type = op.type or op.op
        local result = {index = index, type = op_type}
        
        -- MOVE / TELEPORT
        if op_type == "move" or op_type == "teleport" then
            local pos = get_position(op)
            if not pos then
                result.error = "missing position"
                result.success = false
                return result
            end
            
            local from = {x = character.position.x, y = character.position.y}
            local success = character.teleport(pos)
            
            if success then
                result.success = true
                result.from = from
                result.to = {x = character.position.x, y = character.position.y}
                table.insert(rollback_data, {type = "teleport", position = from})
            else
                result.success = false
                result.error = "teleport failed"
            end
            return result
        end
        
        -- PLACE
        if op_type == "place" then
            local name = op.name
            local pos = get_position(op)
            
            if not name or not pos then
                result.error = "missing name or position"
                result.success = false
                return result
            end
            
            -- Check inventory
            local have = inventory and inventory.get_item_count(name) or 0
            if have == 0 then
                result.error = "no item in inventory"
                result.success = false
                result.item = name
                return result
            end
            
            local direction = DIR_MAP[op.direction] or defines.direction.north
            
            -- Check can place
            local can_place = surface.can_place_entity{
                name = name,
                position = pos,
                direction = direction,
                force = force,
            }
            
            if not can_place then
                result.error = "cannot place at position"
                result.success = false
                result.position = pos
                return result
            end
            
            -- Remove from inventory
            if inventory then
                inventory.remove{name = name, count = 1}
            end
            
            -- Create entity
            local entity = surface.create_entity{
                name = name,
                position = pos,
                direction = direction,
                force = force,
            }
            
            if entity and entity.valid then
                result.success = true
                result.entity = {
                    name = entity.name,
                    type = entity.type,
                    position = {x = entity.position.x, y = entity.position.y},
                }
                table.insert(rollback_data, {
                    type = "remove_entity",
                    entity = entity,
                    item = name,
                })
            else
                -- Rollback item
                if inventory then
                    inventory.insert{name = name, count = 1}
                end
                result.error = "entity creation failed"
                result.success = false
            end
            return result
        end
        
        -- REMOVE
        if op_type == "remove" then
            local pos = get_position(op)
            local name = op.name
            
            if not pos then
                result.error = "missing position"
                result.success = false
                return result
            end
            
            -- Find entity
            local filter = {position = pos, radius = 1.5, force = force}
            if name then filter.name = name end
            
            local entities = surface.find_entities_filtered(filter)
            local target = nil
            local min_dist = math.huge
            
            for _, ent in ipairs(entities) do
                if ent.valid and ent.type ~= "character" and ent.can_be_destroyed() then
                    local d = distance(ent.position, pos)
                    if d < min_dist then
                        min_dist = d
                        target = ent
                    end
                end
            end
            
            if not target then
                result.error = "no entity found at position"
                result.success = false
                return result
            end
            
            local target_name = target.name
            local target_pos = {x = target.position.x, y = target.position.y}
            local count_before = inventory and inventory.get_item_count(target_name) or 0
            
            -- Mine entity
            local mined = character.mine_entity(target, true)
            
            if mined then
                local count_after = inventory and inventory.get_item_count(target_name) or count_before
                local recovered = math.max(0, count_after - count_before)
                result.success = true
                result.entity = target_name
                result.position = target_pos
                if recovered > 0 then
                    result.recovered = {name = target_name, count = recovered}
                end
            else
                result.error = "mining failed"
                result.success = false
            end
            return result
        end
        
        -- INVENTORY_ADD
        if op_type == "inventory_add" then
            local name = op.name
            local count = tonumber(op.count) or 1
            
            if not name then
                result.error = "missing item name"
                result.success = false
                return result
            end
            
            local inserted = character.insert{name = name, count = count}
            result.success = inserted > 0
            result.inserted = inserted
            result.item = name
            return result
        end
        
        -- INVENTORY_REMOVE
        if op_type == "inventory_remove" then
            local name = op.name
            local count = tonumber(op.count) or 1
            
            if not name then
                result.error = "missing item name"
                result.success = false
                return result
            end
            
            if not inventory then
                result.error = "no inventory"
                result.success = false
                return result
            end
            
            local removed = inventory.remove{name = name, count = count}
            result.success = removed > 0
            result.removed = removed
            result.item = name
            
            if removed > 0 then
                table.insert(rollback_data, {
                    type = "inventory_add",
                    name = name,
                    count = removed,
                })
            end
            return result
        end
        
        -- INSPECT
        if op_type == "inspect" then
            local pos = get_position(op)
            local radius = tonumber(op.radius) or 10
            
            if not pos then
                pos = {x = character.position.x, y = character.position.y}
            end
            
            local area = {
                {pos.x - radius, pos.y - radius},
                {pos.x + radius, pos.y + radius},
            }
            
            -- Find entities
            local entities_raw = surface.find_entities_filtered{area = area}
            local entities = {}
            local max_entities = tonumber(op.max_entities) or 30
            
            for i, ent in ipairs(entities_raw) do
                if i > max_entities then break end
                if ent.valid and ent.type ~= "character" then
                    table.insert(entities, {
                        name = ent.name,
                        type = ent.type,
                        position = {x = math.floor(ent.position.x * 10) / 10, y = math.floor(ent.position.y * 10) / 10},
                    })
                end
            end
            
            -- Find resources
            local resources_raw = surface.find_entities_filtered{area = area, type = "resource"}
            local resources = {}
            local max_resources = tonumber(op.max_resources) or 20
            
            for i, res in ipairs(resources_raw) do
                if i > max_resources then break end
                if res.valid then
                    table.insert(resources, {
                        name = res.name,
                        position = {x = res.position.x, y = res.position.y},
                        amount = res.amount,
                    })
                end
            end
            
            result.success = true
            result.entities = entities
            result.entity_count = #entities
            result.resources = resources
            result.resource_count = #resources
            result.center = pos
            result.radius = radius
            return result
        end
        
        -- Unknown operation
        result.error = "unknown operation type: " .. tostring(op_type)
        result.success = false
        return result
    end
    
    -- Execute all operations
    for i, op in ipairs(operations) do
        local result = execute_op(op, i)
        table.insert(results, result)
        
        if result.success then
            success_count = success_count + 1
        else
            failed_count = failed_count + 1
            if stop_on_error then
                break
            end
        end
    end
    
    -- Transaction rollback if any failed
    if transaction and failed_count > 0 then
        -- Rollback in reverse order
        for i = #rollback_data, 1, -1 do
            local rb = rollback_data[i]
            if rb.type == "teleport" then
                character.teleport(rb.position)
            elseif rb.type == "remove_entity" then
                if rb.entity and rb.entity.valid then
                    rb.entity.destroy()
                    if inventory and rb.item then
                        inventory.insert{name = rb.item, count = 1}
                    end
                end
            elseif rb.type == "inventory_add" then
                if inventory then
                    inventory.insert{name = rb.name, count = rb.count}
                end
            end
        end
    end
    
    return serialize({
        ok = true,
        results = results,
        success_count = success_count,
        failed_count = failed_count,
        total_count = #operations,
        executed_count = #results,
        transaction_rolled_back = transaction and failed_count > 0,
    })
end
