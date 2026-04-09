-- Batch budget monitoring with variance analysis for resource consumption vs allocation
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Default parameters
    local radius = args.radius or 50
    local threshold = args.threshold or 0.1  -- 10% variance threshold
    
    -- Get agent position
    local player = game.players[1]
    local surface = player.surface
    local pos = player.position
    
    -- Find all entities in the area (excluding character)
    local entities = surface.find_entities_filtered{
        area = {
            left_top = {x = pos.x - radius, y = pos.y - radius},
            right_bottom = {x = pos.x + radius, y = pos.y + radius}
        },
        invert = true,
        type = "character"
    }
    
    -- Track resource consumption vs allocation
    local budget_data = {}
    local total_consumption = 0
    local total_allocation = 0
    
    for _, entity in ipairs(entities) do
        if entity.valid and entity.type == "assembling-machine" then
            local recipe = entity.get_recipe()
            if recipe then
                -- Calculate consumption based on ingredients
                local consumption = 0
                for ingredient_name, amount in pairs(recipe.ingredients) do
                    consumption = consumption + amount
                end
                
                -- Estimate allocation based on output
                local output = #recipe.results
                local allocation = output * 2  -- Simplified allocation model
                
                total_consumption = total_consumption + consumption
                total_allocation = total_allocation + allocation
                
                table.insert(budget_data, {
                    entity_name = entity.name,
                    position = {x = entity.position.x, y = entity.position.y},
                    consumption = consumption,
                    allocation = allocation,
                    variance = math.abs(consumption - allocation) / allocation
                })
            end
        end
    end
    
    -- Calculate overall variance
    local overall_variance = 0
    if total_allocation > 0 then
        overall_variance = math.abs(total_consumption - total_allocation) / total_allocation
    end
    
    -- Filter items exceeding threshold
    local alerts = {}
    for _, item in ipairs(budget_data) do
        if item.variance > threshold then
            table.insert(alerts, item)
        end
    end
    
    return serialize({
        ok = true,
        total_entities = #entities,
        monitored_machines = #budget_data,
        total_consumption = total_consumption,
        total_allocation = total_allocation,
        overall_variance = overall_variance,
        threshold_exceeded = #alerts,
        alerts = alerts,
        radius = radius,
        threshold = threshold
    })
end
