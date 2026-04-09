-- Batch budget variance analysis for resource consumption vs allocation
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Validate input
    if not args or type(args) ~= "table" then
        return serialize({ok = false, error = "Invalid arguments: expected table"})
    end
    
    if not args.budgets or type(args.budgets) ~= "table" then
        return serialize({ok = false, error = "Missing 'budgets' array in arguments"})
    end
    
    -- Get agent position for reference
    local player = game.players[1]
    local agent_pos = nil
    if player and player.valid then
        agent_pos = {x = player.position.x, y = player.position.y}
    end
    
    -- Process each budget item
    local results = {}
    local total_variance = 0
    local significant_variances = 0
    
    for i, budget_item in ipairs(args.budgets) do
        if type(budget_item) ~= "table" then
            results[i] = {error = "Invalid budget item at index " .. i}
            goto continue
        end
        
        local resource_name = budget_item.resource_name
        local allocated = budget_item.allocated or 0
        local consumed = budget_item.consumed or 0
        local threshold = budget_item.threshold or 0.1  -- 10% default threshold
        
        if not resource_name then
            results[i] = {error = "Missing 'resource_name' in budget item " .. i}
            goto continue
        end
        
        if type(allocated) ~= "number" or type(consumed) ~= "number" then
            results[i] = {error = "Invalid numbers in budget item " .. i}
            goto continue
        end
        
        -- Calculate variance
        local variance_amount = consumed - allocated
        local variance_percentage = 0
        if allocated > 0 then
            variance_percentage = variance_amount / allocated
        elseif consumed > 0 then
            -- If allocated is 0 but consumed > 0, treat as infinite variance
            variance_percentage = math.huge
        end
        
        -- Check if variance is significant
        local is_significant = math.abs(variance_percentage) > threshold
        
        results[i] = {
            resource_name = resource_name,
            allocated = allocated,
            consumed = consumed,
            variance_amount = variance_amount,
            variance_percentage = variance_percentage,
            is_significant = is_significant,
            threshold = threshold
        }
        
        total_variance = total_variance + math.abs(variance_amount)
        if is_significant then
            significant_variances = significant_variances + 1
        end
        
        ::continue::
    end
    
    -- Summary statistics
    local summary = {
        total_items = #args.budgets,
        items_with_errors = 0,
        significant_variances = significant_variances,
        total_variance_magnitude = total_variance,
        average_variance_percentage = #results > 0 and (total_variance / #results) or 0
    }
    
    -- Count errors
    for _, result in ipairs(results) do
        if result.error then
            summary.items_with_errors = summary.items_with_errors + 1
        end
    end
    
    return serialize({
        ok = true,
        results = results,
        summary = summary,
        agent_position = agent_pos,
        timestamp = game.tick
    })
end
