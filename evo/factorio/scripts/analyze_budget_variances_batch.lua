-- Batch budget variance analysis for resource consumption vs allocation
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Validate input structure
    if not args.budgets or type(args.budgets) ~= "table" then
        return serialize({error = "missing or invalid 'budgets' array"})
    end
    
    local results = {}
    local total_variance = 0
    local significant_variances = {}
    local categories = {}
    
    -- Process each budget item
    for i, budget_item in ipairs(args.budgets) do
        if type(budget_item) ~= "table" then
            table.insert(results, {error = "invalid budget item at index " .. i})
        else
            local item_name = budget_item.item
            local allocated = budget_item.allocated or 0
            local actual = budget_item.actual or 0
            local category = budget_item.category or "uncategorized"
            
            if not item_name then
                table.insert(results, {error = "missing item name at index " .. i})
            else
                local variance = actual - allocated
                local variance_pct = allocated > 0 and (variance / allocated * 100) or (actual > 0 and 100 or 0)
                
                local result = {
                    item = item_name,
                    category = category,
                    allocated = allocated,
                    actual = actual,
                    variance = variance,
                    variance_pct = variance_pct,
                    status = "ok"
                }
                
                -- Flag significant variances (>15% or absolute >200)
                if math.abs(variance_pct) > 15 or math.abs(variance) > 200 then
                    result.significant = true
                    table.insert(significant_variances, result)
                end
                
                -- Track by category
                if not categories[category] then
                    categories[category] = {
                        allocated_total = 0,
                        actual_total = 0,
                        items = 0,
                        significant_items = 0
                    }
                end
                categories[category].allocated_total = categories[category].allocated_total + allocated
                categories[category].actual_total = categories[category].actual_total + actual
                categories[category].items = categories[category].items + 1
                if result.significant then
                    categories[category].significant_items = categories[category].significant_items + 1
                end
                
                total_variance = total_variance + variance
                table.insert(results, result)
            end
        end
    end
    
    -- Calculate category summaries
    local category_summaries = {}
    for category_name, category_data in pairs(categories) do
        local cat_variance = category_data.actual_total - category_data.allocated_total
        local cat_variance_pct = category_data.allocated_total > 0 and 
            (cat_variance / category_data.allocated_total * 100) or 
            (category_data.actual_total > 0 and 100 or 0)
        
        category_summaries[category_name] = {
            allocated_total = category_data.allocated_total,
            actual_total = category_data.actual_total,
            variance = cat_variance,
            variance_pct = cat_variance_pct,
            items_count = category_data.items,
            significant_items_count = category_data.significant_items,
            over_budget = cat_variance > 0
        }
    end
    
    -- Calculate overall summary statistics
    local summary = {
        total_items = #args.budgets,
        items_with_errors = 0,
        total_variance = total_variance,
        significant_count = #significant_variances,
        categories_count = 0,
        over_budget_categories = 0
    }
    
    -- Count errors and category stats
    for _, result in ipairs(results) do
        if result.error then
            summary.items_with_errors = summary.items_with_errors + 1
        end
    end
    
    for category_name, category_summary in pairs(category_summaries) do
        summary.categories_count = summary.categories_count + 1
        if category_summary.over_budget then
            summary.over_budget_categories = summary.over_budget_categories + 1
        end
    end
    
    return serialize({
        ok = true,
        summary = summary,
        results = results,
        significant_variances = significant_variances,
        categories = category_summaries
    })
end
