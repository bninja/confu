function confue {
    declare -a in_args=( "$@" )
    declare -i i=0
    declare name
    declare profile
    declare region
    declare log_level

    while [ $i -lt $# ]
    do
        a="${in_args[$i]}"
        case "$a" in
            -p|--profile)
                i=$(( $i + 1 ));
                profile="${in_args[$i]}"
                confue_set profile $profile;;
            -r|--region)
                i=$(( $i + 1 ));
                region="${in_args[$i]}"
                confue_set region $region;;
            -l|--log|--log-level)
                i=$(( $i + 1 ));
                log="${in_args[$i]}"
                confue_set log $log;;
            stat)
                confue_stat;;
            reset)
                confue_reset;;
            ls)
                confue_ls;;
            rm)
                i=$(( $i + 1 ));
                name="${in_args[$i]}"
                confue_rm $name;;
            pop)
                confue_deactivate;;
            -h|--help)
                confue_help;;
            *)
                confue_activate $a;;
        esac
        i=$(( $i + 1 ));
    done
        
    if [[ 0 -eq $# ]]
    then
        confue_stat
    fi
}

function confue_help {
    echo "Usage: confue [OPTIONS] [COMMAND] [ARGS]"
    echo ""
    echo "Options:"
    echo "  -p, --profile PROFILE-NAME"
    echo "  -r, --region REGION-NAME"
    echo "  -l, --log, --log-level LOG-LEVEL"
    echo ""
    echo "Commands:"
    echo "  stat"
    echo "  reset"
    echo "  ls"
    echo "  [NAME]"
    echo "  rm [NAME]"
    echo "  pop"
}


function confue_set {
    declare name="$1"
    declare value="$2"
    
    case "$name" in
        profile)
            export CONFU_PROFILE="$value";;
        region)
            export CONFU_REGION="$value";;
        log)
            export CONFU_LOG="$value";;
    esac
    if confue_is_activated;
    then
        confue_write
    fi
}

function confue_reset {
    unset CONFU_PROFILE
    unset CONFU_REGION
    unset CONFU_LOG
}

function confue_stat {
    echo "CONFUE_NAME=${CONFUE_NAME:-}"
    echo "CONFU_PROFILE=${CONFU_PROFILE:-}"
    echo "CONFU_REGION=${CONFU_REGION:-}"
    echo "CONFU_LOG=${CONFU_LOG:-}"
}

function confue_ls {
    declare env_dir="${HOME}/.confu/e"
    
    ls "$env_dir"
}

function confue_rm {
    declare name="$1"
    declare env_dir="${HOME}/.confu/e"
    declare env_file="${env_dir}/${name}"
    
    if [ -f "$env_file" ]
    then
        rm "$env_file"
    fi
}

function confue_is_activated {
    if [ -z "${CONFUE_NAME:-}" ]
    then
        return 1
    else
        return 0
    fi
}

function confue_activate {
    declare name="$1"
    declare env_dir="${HOME}/.confu/e"
    declare env_file="${env_dir}/${name}"

    if [ -f "$env_file" ]
    then
        source "$env_file"
    else
        confue_deactivate
    fi
    export CONFUE_NAME="$name"
}

function confue_write {   
    declare env_dir="${HOME}/.confu/e"
    declare env_file="${env_dir}/${CONFUE_NAME:-}"
    
    if [ ! -d "$env_dir" ]
    then
        mkdir -p "$env_dir"
    fi

    cat > "$env_file" <<EOF
export CONFU_PROFILE="${CONFU_PROFILE:-}"
export CONFU_REGION="${CONFU_REGION:-}"
export CONFU_LOG="${CONFU_LOG:-}"
EOF
}

function confue_deactivate {
    unset CONFUE_NAME
    confue_reset
}
